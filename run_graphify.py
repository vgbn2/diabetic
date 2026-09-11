import os
import json
from pathlib import Path

def run_pipeline():
    try:
        from graphify.detect import detect
        from graphify.extract import collect_files, extract
        from graphify.build import build_from_json
        from graphify.cluster import cluster, score_all
        from graphify.analyze import god_nodes, surprising_connections, suggest_questions
        from graphify.report import generate
        from graphify.export import to_json
    except ImportError:
        print("Error: Could not import 'graphify'. Please run: pip install graphifyy")
        return

    project_root = Path('.')
    os.makedirs('graphify-out', exist_ok=True)
    
    # Step 1: Detect
    print("Detecting files...")
    detect_res = detect(project_root)
    Path('graphify-out/.graphify_detect.json').write_text(json.dumps(detect_res), encoding='utf-8')
    
    # Step 2: AST Extraction
    print("Extracting AST (Structural)...")
    code_files = []
    for f in detect_res.get('files', {}).get('code', []):
        p = Path(f)
        code_files.extend(collect_files(p) if p.is_dir() else [p])
    
    if code_files:
        ast_res = extract(code_files, cache_root=project_root)
        Path('graphify-out/.graphify_ast.json').write_text(json.dumps(ast_res, indent=2), encoding='utf-8')
        print(f"AST Extraction: {len(ast_res.get('nodes', []))} nodes, {len(ast_res.get('edges', []))} edges")
    else:
        ast_res = {'nodes':[], 'edges':[], 'input_tokens':0, 'output_tokens':0}
        
    # Step 3: Semantic Extraction (LLM)
    all_files = [Path(f) for files in detect_res.get('files', {}).values() for f in files]
    semantic_res = {'nodes':[], 'edges':[], 'hyperedges':[], 'input_tokens':0, 'output_tokens':0}
    
    if os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY'):
        print("Extracting Semantic Knowledge (LLM)...")
        try:
            from graphify.llm import extract_corpus_parallel
            semantic_res = extract_corpus_parallel(all_files, backend="gemini")
        except ImportError:
            print("graphify[gemini] not installed or extract_corpus_parallel unavailable. Skipping semantic extraction.")
    else:
        print("No GEMINI_API_KEY set. Skipping semantic extraction.")

    # Merge
    print("Merging graphs...")
    seen = {n['id'] for n in ast_res.get('nodes', [])}
    merged_nodes = list(ast_res.get('nodes', []))
    for n in semantic_res.get('nodes', []):
        if n['id'] not in seen:
            merged_nodes.append(n)
            seen.add(n['id'])
            
    merged_edges = ast_res.get('edges', []) + semantic_res.get('edges', [])
    extraction = {
        'nodes': merged_nodes,
        'edges': merged_edges,
        'hyperedges': semantic_res.get('hyperedges', []),
        'input_tokens': semantic_res.get('input_tokens', 0),
        'output_tokens': semantic_res.get('output_tokens', 0)
    }
    Path('graphify-out/.graphify_extract.json').write_text(json.dumps(extraction, indent=2), encoding='utf-8')
    
    if not extraction['nodes']:
        print("ERROR: Graph is empty - extraction produced no nodes.")
        return

    # Build and cluster
    print("Building and clustering graph...")
    G = build_from_json(extraction)
    communities = cluster(G)
    cohesion = score_all(G, communities)
    
    gods = god_nodes(G)
    surprises = surprising_connections(G, communities)
    labels = {cid: f'Community {cid}' for cid in communities}
    questions = suggest_questions(G, communities, labels)
    
    print("Generating report and outputs...")
    tokens = {'input': extraction.get('input_tokens', 0), 'output': extraction.get('output_tokens', 0)}
    report = generate(G, communities, cohesion, labels, gods, surprises, detect_res, tokens, str(project_root.absolute()), suggested_questions=questions)
    
    Path('graphify-out/GRAPH_REPORT.md').write_text(report, encoding='utf-8')
    to_json(G, communities, 'graphify-out/graph.json')
    
    # Save analysis
    analysis = {
        'communities': {str(k): v for k, v in communities.items()},
        'cohesion': {str(k): v for k, v in cohesion.items()},
        'gods': gods,
        'surprises': surprises,
        'questions': questions,
    }
    Path('graphify-out/.graphify_analysis.json').write_text(json.dumps(analysis, indent=2), encoding='utf-8')
    
    print(f"Graph complete: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges, {len(communities)} communities.")
    print("Outputs written to graphify-out/")

if __name__ == '__main__':
    run_pipeline()
