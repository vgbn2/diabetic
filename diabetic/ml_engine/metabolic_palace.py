import os
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

try:
    import chromadb
    # mempalace removed [B1]
    search_memories = None
    LOCAL_PALACE_CONFIG = None
except ImportError:
    # Fallback for environment verification
    chromadb = None
    LOCAL_PALACE_CONFIG = None

logger = logging.getLogger("diabetic.memory")

class MetabolicPalace:
    """
    The Metabolic Oracle's memory core.
    Provides semantic recall for clinical events, anomalies, and user feedback.
    """
    
    def __init__(self, palace_path: Optional[str] = None):
        self.palace_path = palace_path or str(Path.home() / ".mempalace" / "palace")#is this needed?
        self.wing = "hyperglycemia_faint_predictor"
        self._ensure_init()
        
        # Load taxonomy
        tax_path = Path(__file__).parent / "metabolic_taxonomy.json"
        with open(tax_path, "r") as f:
            self.taxonomy = json.load(f)
            
    def _ensure_init(self):
        if not os.path.exists(self.palace_path):
            logger.warning(f"Metabolic Palace not found at {self.palace_path}. Interaction will be transient.")

    def remember_snapshot(self, snapshot: Dict[str, Any], room: str = "l4_anomaly_audit"):
        """
        Indexes a metabolic snapshot into the palace.
        Converts the dict into a text 'drawer' for semantic search.
        """
        if not chromadb:
            return
            
        timestamp = snapshot.get("timestamp", datetime.now().isoformat())
        # Convert snapshot to a descriptive text string for embedding
        lines = [f"Metabolic Snapshot at {timestamp}"]
        for k, v in snapshot.items():
            if k != "timestamp":
                lines.append(f"{k}: {v}")
        
        content = "\n".join(lines)
        
        # We manually inject into the chroma collection used by mempalace
        try:
            client = chromadb.PersistentClient(path=self.palace_path)
            col = client.get_or_create_collection("mempalace_drawers")
            
            doc_id = f"metabolic_{timestamp}_{room}"
            col.add(
                documents=[content],
                ids=[doc_id],
                metadatas=[{
                    "wing": self.wing,
                    "room": room,
                    "source_file": "live_coordinator",
                    "type": "metabolic_snapshot",
                    "timestamp": timestamp
                }]
            )
            logger.info(f"Metabolic memory indexed in {room}: {doc_id}")
        except Exception as e:
            logger.error(f"Failed to index metabolic memory: {e}")

    def recall_patterns(self, query: str, room: Optional[str] = None, n: int = 3) -> List[Dict[str, Any]]:
        """
        Searches memory for clinical correlations.
        """
        try:
            return search_memories(
                query=query,
                palace_path=self.palace_path,
                wing=self.wing,
                room=room,
                n_results=n
            ).get("results", [])
        except Exception as e:
            logger.error(f"Recall failed: {e}")
            return []

    def get_context_for_pred(self, current_vitals: Dict[str, Any]) -> str:
        """
        Retrieves relevant historical context for current prediction.
        """
        # Formulate query based on vital triggers
        triggers = []
        if current_vitals.get("glucose", 0) > 15.0:
            triggers.append("high blood sugar")
        if current_vitals.get("hrv", 100) < 30:
            triggers.append("hrv drop distress")
            
        if not triggers:
            return ""
            
        query = " ".join(triggers)
        past_hits = self.recall_patterns(query, n=2)
        
        if not past_hits:
            return ""
            
        context = "\n[Historical Context]:\n"
        for hit in past_hits:
            context += f"- {hit['text']}\n"
        return context
