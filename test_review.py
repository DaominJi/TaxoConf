#!/usr/bin/env python3
"""
Diagnostic script to test the LLM session review in isolation.

Usage:
    python test_review.py

This will:
  1. Load papers from the first available conference dataset
  2. Build a quick auto-taxonomy and run oral organization
  3. Call the LLM session reviewer and print detailed diagnostics
  4. Save the full prompt and response to test_review_debug.json
"""
import json
import logging
import os
import sys
from pathlib import Path

# Setup logging to see everything
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_review")

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import config
from taxonomy_builder import LLMClient
from session_reviewer import (
    review_sessions,
    _build_session_directory,
    _build_sessions_block,
    _chunk_sessions,
    REVIEW_SYSTEM_PROMPT,
    REVIEW_USER_PROMPT,
)


def main():
    # ── Step 1: Check API keys ────────────────────────────────────
    print("=" * 60)
    print("STEP 1: Checking LLM API keys")
    print("=" * 60)

    key_vars = ["OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY",
                "ANTHROPIC_API_KEY", "XAI_API_KEY"]
    found_keys = []
    for k in key_vars:
        val = os.environ.get(k, "")
        if val:
            found_keys.append(k)
            print(f"  {k}: SET ({len(val)} chars, starts with {val[:8]}...)")
        else:
            print(f"  {k}: NOT SET")

    if not found_keys:
        print("\n*** ERROR: No LLM API key is configured! ***")
        print("The session reviewer requires an LLM. Set one of:")
        for k in key_vars:
            print(f"  export {k}=your_key_here")
        return

    # ── Step 2: Initialize LLM client ─────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 2: Initializing LLM client")
    print("=" * 60)

    try:
        llm = LLMClient()
        print(f"  Provider: {llm.provider}")
        print(f"  Model:    {llm.model}")
    except Exception as e:
        print(f"\n*** ERROR initializing LLM client: {e} ***")
        import traceback
        traceback.print_exc()
        return

    # ── Step 3: Test basic LLM call ───────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 3: Testing basic LLM call")
    print("=" * 60)

    try:
        test_response = llm.chat(
            "You are a test assistant.",
            "Reply with exactly: TEST_OK",
            call_label="connectivity_test",
        )
        print(f"  LLM response: {test_response.strip()}")
        print("  Basic LLM call: OK")
    except Exception as e:
        print(f"\n*** ERROR: LLM call failed: {e} ***")
        import traceback
        traceback.print_exc()
        return

    # ── Step 4: Build test sessions ───────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 4: Building test sessions for review")
    print("=" * 60)

    # Use a small set of clearly distinguishable sessions
    test_sessions = [
        {
            "id": "slot_1_track_1",
            "sessionName": "Dense Retrieval & Neural Ranking",
            "papers": [
                {"id": "101", "title": "ColBERT: Efficient and Effective Passage Search via Contextualized Late Interaction over BERT"},
                {"id": "102", "title": "Dense Passage Retrieval for Open-Domain Question Answering"},
                {"id": "103", "title": "Approximate Nearest Neighbor Negative Contrastive Learning for Dense Text Retrieval"},
                {"id": "104", "title": "Image Classification with Convolutional Neural Networks on CIFAR-10"},  # MISPLACED
            ],
        },
        {
            "id": "slot_1_track_2",
            "sessionName": "Recommendation Systems",
            "papers": [
                {"id": "201", "title": "Self-Attentive Sequential Recommendation"},
                {"id": "202", "title": "Neural Collaborative Filtering"},
                {"id": "203", "title": "LightGCN: Simplifying and Powering Graph Convolution Network for Recommendation"},
            ],
        },
        {
            "id": "slot_2_track_1",
            "sessionName": "Computer Vision & Image Processing",
            "papers": [
                {"id": "301", "title": "Vision Transformer for Image Recognition"},
                {"id": "302", "title": "Object Detection with YOLO v5"},
                {"id": "303", "title": "Query Likelihood Model for Information Retrieval"},  # MISPLACED
            ],
        },
        {
            "id": "slot_2_track_2",
            "sessionName": "Fairness & Bias in AI",
            "papers": [
                {"id": "401", "title": "Mitigating Gender Bias in Natural Language Processing"},
                {"id": "402", "title": "Fair Ranking: A Critical Review"},
            ],
        },
    ]

    print(f"  Created {len(test_sessions)} test sessions with "
          f"{sum(len(s['papers']) for s in test_sessions)} papers")
    print("  (Paper 104 and 303 are intentionally misplaced)")

    # ── Step 5: Build and display the prompt ──────────────────────
    print("\n" + "=" * 60)
    print("STEP 5: Building prompt")
    print("=" * 60)

    session_directory = _build_session_directory(test_sessions)
    sessions_block = _build_sessions_block(test_sessions)
    full_prompt = REVIEW_USER_PROMPT.format(
        session_directory=session_directory,
        sessions_block=sessions_block,
    )

    print(f"  System prompt length: {len(REVIEW_SYSTEM_PROMPT)} chars")
    print(f"  User prompt length: {len(full_prompt)} chars")
    print(f"  Session directory:\n{session_directory}")

    # ── Step 6: Call the LLM for session review ───────────────────
    print("\n" + "=" * 60)
    print("STEP 6: Calling LLM for session review")
    print("=" * 60)

    try:
        raw_response = llm.chat(
            REVIEW_SYSTEM_PROMPT,
            full_prompt,
            call_label="diagnostic_test",
        )
        print(f"  Raw response length: {len(raw_response)} chars")
        print(f"  Raw response:\n{'─' * 40}")
        print(raw_response)
        print(f"{'─' * 40}")
    except Exception as e:
        print(f"\n*** ERROR: LLM review call failed: {e} ***")
        import traceback
        traceback.print_exc()
        return

    # ── Step 7: Parse and display results ─────────────────────────
    print("\n" + "=" * 60)
    print("STEP 7: Running full review_sessions()")
    print("=" * 60)

    hard_papers = review_sessions(
        llm, test_sessions, all_sessions=test_sessions, mode="oral"
    )

    print(f"\n  Flagged papers: {len(hard_papers)}")
    for hp in hard_papers:
        print(f"\n  Paper {hp['paper_id']}: {hp['title']}")
        print(f"    Current session: {hp['current_session_name']} ({hp['current_session_id']})")
        print(f"    Reason: {hp['difficultyReason']}")
        print(f"    Suggested action: {hp['suggestedAction']}")
        print(f"    Top alternatives ({len(hp['alternative_sessions'])}):")
        for i, alt in enumerate(hp["alternative_sessions"][:5], 1):
            print(f"      {i}. [{alt['session_id']}] {alt['session_name']}")

    # ── Step 8: Save debug data ───────────────────────────────────
    debug_path = PROJECT_ROOT / "test_review_debug.json"
    debug_data = {
        "provider": llm.provider,
        "model": llm.model,
        "system_prompt": REVIEW_SYSTEM_PROMPT,
        "user_prompt": full_prompt,
        "raw_response": raw_response,
        "parsed_hard_papers": hard_papers,
        "test_sessions": test_sessions,
    }
    with open(debug_path, "w") as f:
        json.dump(debug_data, f, indent=2, ensure_ascii=False)
    print(f"\n  Debug data saved to: {debug_path}")

    # ── Summary ───────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    if len(hard_papers) >= 2:
        print("  ✓ LLM correctly identified misplaced papers.")
        print("  The session review is working. If it returns empty with")
        print("  real data, the LLM may think the real sessions are fine.")
    elif len(hard_papers) == 0:
        print("  ✗ LLM returned NO flagged papers despite obvious mismatches.")
        print("  Possible causes:")
        print("    - The model may not be following JSON output instructions")
        print("    - The response may have been truncated")
        print("    - Check the raw response above for clues")
    else:
        print(f"  ~ LLM found {len(hard_papers)} paper(s). Expected 2.")
        print("  Partial detection — review the output above.")


if __name__ == "__main__":
    main()
