---
phase: 10
plan: 1
type: tdd
wave: 1
depends_on: []
files_modified: ["requirements.txt", "diabetic/ml_engine/convolutional_layer.py", "ops/lab/test_cnn_layer.py"]
autonomous: true

must_haves:
  truths:
    - "PyTorch is installed"
    - "CNN takes (Batch, Channels, TimeSteps) and (Batch, StaticFeatures) and outputs a scalar residual"
    - "Gradients flow properly through the network in a backward pass"
  artifacts:
    - "diabetic/ml_engine/convolutional_layer.py"
    - "ops/lab/test_cnn_layer.py"
---

# TDD Plan 10.1: Scaffold Hybrid CNN+LSTM Oracle

<objective>
To lay the mathematical foundation for the Layer 1-4 predictive model by implementing a PyTorch network combining a 1D-CNN, an LSTM, and an MLP.

Purpose: We need the skeletal architecture of the intelligence engine capable of fusing temporal sensor traces with static bio-vectors.
Output: Initial `DiabeticCNN` neural network class and a passing test script using mock tensors.
</objective>

<context>
Load for context:
- ML_SPEC.md (To understand the 4-layer separation: Layer 1 = temporal, Layers 2/3 = static)
- requirements.txt
</context>

## Red Phase
<task type="auto">
  <name>Write failing tests for DiabeticCNN</name>
  <files>ops/lab/test_cnn_layer.py</files>
  <action>
    Create a test script that instantiates `DiabeticCNN(temporal_channels=2, static_features=15)`.
    Generate mock input tensors: `temporal_x` shape (16, 2, 30) representing [Batch, Features(BG+HR), TimeSteps(30)] and `static_y` shape (16, 15).
    Assert that the forward pass outputs shape (16, 1).
    Assert that `loss.backward()` calculates gradients without errors.
    AVOID: Actually training the model; just verify the forward/backward shapes and graph connectivity.
  </action>
  <verify>python ops/lab/test_cnn_layer.py</verify>
  <done>Script fails because `DiabeticCNN` doesn't exist yet.</done>
</task>

## Green Phase
<task type="auto">
  <name>Install dependencies & Implement CNN</name>
  <files>requirements.txt, diabetic/ml_engine/convolutional_layer.py</files>
  <action>
    Add `torch>=2.0.0` to requirements.txt.
    Implement `DiabeticCNN` in `convolutional_layer.py`.
    Architecture:
    1. Extract features from `temporal_x` using `nn.Conv1d` -> `nn.ReLU` -> `nn.MaxPool1d`, then passing to an `nn.LSTM`.
    2. Extract latest hidden state from LSTM.
    3. Pass `static_y` through an `nn.Sequential` (MLP) mapping to an embedding.
    4. Concatenate both embeddings and pass through a final Output Head (`nn.Linear` mapping to 1).
  </action>
  <verify>python ops/lab/test_cnn_layer.py</verify>
  <done>Network compiles, inputs match outputs, backward pass yields gradients.</done>
</task>

## Refactor Phase
<task type="auto">
  <name>Clean architecture</name>
  <files>diabetic/ml_engine/convolutional_layer.py</files>
  <action>
    Ensure parameters are configurable (e.g., `lstm_hidden_size`, `cnn_channels`) using Pydantic or basic dataclasses to allow hyperparameter tuning later.
  </action>
  <verify>python ops/lab/test_cnn_layer.py</verify>
  <done>Test remains GREEN.</done>
</task>
