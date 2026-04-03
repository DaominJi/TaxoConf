"""
LLM-based session reviewer.

After oral or poster sessions have been organized, this module asks the LLM
to inspect each session and flag papers that do not fit well.  The output
is a list of "hard paper" records that the frontend can display for
last-mile manual editing.

Usage:
    from session_reviewer import review_sessions
    hard_papers = review_sessions(llm, sessions_data, mode="oral")

``sessions_data`` is a list of dicts, each with at least:
    - session_id, session_name
    - papers: list[{id, title, authors/presenters}]
"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────
# Prompt templates
# ────────────────────────────────────────────────────────────────────

REVIEW_SYSTEM_PROMPT = """\
You are an expert conference program chair reviewing the final session \
assignments of an academic conference.  Your job is to look at each session \
and identify any papers whose topic does NOT fit well with the rest of the \
session.  A paper is "misplaced" when its research topic is clearly \
different from the dominant theme of its session.

For every misplaced paper you find, you must:
1. Explain WHY it does not belong in its current session.
2. Recommend the top-5 best-fitting alternative sessions (ranked from best \
to worst) from the FULL SESSION DIRECTORY provided, with a brief reason \
for each."""

REVIEW_USER_PROMPT = """\
=== FULL SESSION DIRECTORY ===
The following is the complete list of ALL sessions at this conference.  Use \
this directory when recommending top-5 alternative sessions for misplaced \
papers.

{session_directory}

=== SESSIONS TO REVIEW ===
Below are the sessions you must review.  For each session, check whether \
all assigned papers share a coherent topical theme.  Flag any paper that \
does not fit.

{sessions_block}

Return a JSON array (possibly empty) of objects, one per misplaced paper:
```json
[
  {{
    "paper_id": "<id of the misplaced paper>",
    "current_session_id": "<session id it is currently in>",
    "reason": "<2-3 sentence detailed explanation of why this paper does not fit the session's dominant theme, referencing the session topic and the paper's actual topic>",
    "suggested_action": "<a concise overall recommendation>",
    "top5_sessions": [
      {{
        "session_id": "<id of the best alternative session from the FULL directory>",
        "session_name": "<name of that session>",
        "fit_reason": "<why this session is a good fit for the paper>"
      }},
      {{
        "session_id": "<2nd best>",
        "session_name": "<name>",
        "fit_reason": "<reason>"
      }},
      {{
        "session_id": "<3rd best>",
        "session_name": "<name>",
        "fit_reason": "<reason>"
      }},
      {{
        "session_id": "<4th best>",
        "session_name": "<name>",
        "fit_reason": "<reason>"
      }},
      {{
        "session_id": "<5th best>",
        "session_name": "<name>",
        "fit_reason": "<reason>"
      }}
    ]
  }}
]
```

Rules:
- Only flag papers that are genuinely out of place.  Most papers should fit.
- Do NOT flag a paper just because its sub-topic is slightly different; \
only flag clear mismatches.
- You SHOULD find at least a few misplaced papers across all sessions — it \
is very unlikely that every single paper is perfectly placed.  Look \
carefully at each session's dominant theme and flag any paper whose primary \
research topic is a poor match.
- The "reason" field must be detailed: mention the session's dominant theme, \
what the paper is actually about, and why there is a mismatch.
- The "top5_sessions" must contain exactly 5 entries, ranked from best to \
worst fit.  Each entry MUST reference a real session id and name from the \
FULL SESSION DIRECTORY above, and include a brief "fit_reason" explaining \
why that session would be suitable.
- If you truly believe every paper in every session fits well, return an \
empty array `[]`, but this should be EXTREMELY rare — there are almost \
always at least 3-5 misplaced papers across a full conference program.
- Aim to flag roughly 5-10%% of papers as potentially misplaced.
- Return ONLY the JSON array, no other text."""


def _build_session_directory(all_sessions: list[dict]) -> str:
    """Build a compact directory of all sessions (id + name only).

    This is included in every LLM call so the model always knows the full
    landscape of sessions when suggesting alternatives.
    """
    lines = []
    for s in all_sessions:
        sid = s.get("id") or s.get("session_id", "?")
        sname = s.get("sessionName") or s.get("session_name", "Unnamed")
        n_papers = len(s.get("papers", []))
        lines.append(f"  [{sid}] {sname}  ({n_papers} papers)")
    return "\n".join(lines)


def _build_sessions_block(sessions_data: list[dict]) -> str:
    """Format sessions into a readable text block for the LLM prompt."""
    parts = []
    for s in sessions_data:
        sid = s.get("id") or s.get("session_id", "?")
        sname = s.get("sessionName") or s.get("session_name", "Unnamed")
        papers = s.get("papers", [])
        lines = [f"Session: {sname}  (id: {sid})"]
        for p in papers:
            pid = p.get("id", "?")
            title = p.get("title", "Untitled")
            lines.append(f"  - [{pid}] {title}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _chunk_sessions(sessions_data: list[dict], max_papers_per_chunk: int = 120
                    ) -> list[list[dict]]:
    """Split sessions into chunks so each chunk stays within a reasonable
    token budget for LLM calls."""
    chunks: list[list[dict]] = []
    current: list[dict] = []
    current_count = 0
    for s in sessions_data:
        n = len(s.get("papers", []))
        if current and current_count + n > max_papers_per_chunk:
            chunks.append(current)
            current = []
            current_count = 0
        current.append(s)
        current_count += n
    if current:
        chunks.append(current)
    return chunks


def _parse_llm_response(raw: str) -> list[dict]:
    """Extract flagged papers from the LLM response, tolerating various formats."""
    import re
    text = raw.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        first_nl = text.index("\n") if "\n" in text else 3
        text = text[first_nl + 1:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # 1. Try direct parse — works for arrays, single objects, etc.
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return [r for r in result if isinstance(r, dict) and r.get("paper_id")]
        if isinstance(result, dict):
            if result.get("paper_id"):
                return [result]
            # Wrapper object with a list key
            for key in ("flagged_papers", "papers", "results", "flags", "misplaced_papers",
                        "hard_papers", "flagged", "misplaced"):
                if key in result and isinstance(result[key], list):
                    return [r for r in result[key] if isinstance(r, dict) and r.get("paper_id")]
            # If the dict has any list values containing paper_id dicts, use the first one
            for key, val in result.items():
                if isinstance(val, list) and val and isinstance(val[0], dict) and val[0].get("paper_id"):
                    logger.info(f"  Found flagged papers under unexpected key '{key}'")
                    return [r for r in val if isinstance(r, dict) and r.get("paper_id")]
    except json.JSONDecodeError:
        pass

    # 2. Try extracting a top-level JSON array (skip brackets inside string values)
    #    Find the first '[' that isn't preceded by ': "' context (heuristic)
    arr_start = text.find("[")
    if arr_start == 0 or (arr_start > 0 and text[arr_start - 1] in ("\n", " ", ",")):
        arr_end = text.rfind("]")
        if arr_end > arr_start:
            try:
                result = json.loads(text[arr_start:arr_end + 1])
                if isinstance(result, list):
                    return [r for r in result if isinstance(r, dict) and r.get("paper_id")]
            except json.JSONDecodeError:
                pass

    # 3. Regex fallback: find all {...} objects containing "paper_id"
    objects = re.findall(r'\{[^{}]*"paper_id"[^{}]*\}', text)
    results = []
    for obj_str in objects:
        try:
            obj = json.loads(obj_str)
            if isinstance(obj, dict) and obj.get("paper_id"):
                results.append(obj)
        except json.JSONDecodeError:
            continue
    if results:
        return results

    logger.warning(f"LLM session review returned unparseable response: {text[:200]}...")
    return []


def review_sessions(llm, sessions_data: list[dict],
                    all_sessions: Optional[list[dict]] = None,
                    mode: str = "oral") -> list[dict]:
    """Ask the LLM to review sessions and flag misplaced papers.

    Parameters
    ----------
    llm : LLMClient
        Initialized LLM client.
    sessions_data : list[dict]
        Each dict has keys: id/session_id, sessionName/session_name,
        papers (list of {id, title}).
    all_sessions : list[dict] | None
        Full session list (used to build the session directory and to
        populate alternative_sessions).  Defaults to *sessions_data*.
    mode : str
        "oral" or "poster" — used only for the call_label.

    Returns
    -------
    list[dict]
        Hard paper records compatible with the frontend:
        ``{paper_id, title, current_session_id, current_session_name,
           difficultyReason, suggestedAction, alternative_sessions}``.
    """
    if all_sessions is None:
        all_sessions = sessions_data

    # Build lookup tables
    session_name_map: dict[str, str] = {}
    paper_title_map: dict[str, str] = {}
    paper_session_map: dict[str, str] = {}   # paper_id → session_id

    for s in all_sessions:
        sid = s.get("id") or s.get("session_id", "")
        sname = s.get("sessionName") or s.get("session_name", "")
        session_name_map[sid] = sname
        for p in s.get("papers", []):
            pid = str(p.get("id", ""))
            paper_title_map[pid] = p.get("title", "")
            paper_session_map[pid] = sid

    # Build a compact directory of ALL sessions (always included in prompt)
    session_directory = _build_session_directory(all_sessions)

    # Chunk sessions to avoid overly long prompts
    chunks = _chunk_sessions(sessions_data, max_papers_per_chunk=120)
    raw_flags: list[dict] = []

    logger.info(f"LLM session review ({mode}): reviewing {len(sessions_data)} "
                f"sessions in {len(chunks)} chunk(s)")

    for i, chunk in enumerate(chunks):
        block = _build_sessions_block(chunk)
        prompt = REVIEW_USER_PROMPT.format(
            session_directory=session_directory,
            sessions_block=block,
        )
        label = f"{mode}_session_review_{i + 1}_of_{len(chunks)}"
        try:
            logger.info(f"  Chunk {i + 1}/{len(chunks)}: "
                        f"{len(chunk)} sessions, "
                        f"{sum(len(s.get('papers', [])) for s in chunk)} papers")
            response = llm.chat(REVIEW_SYSTEM_PROMPT, prompt, call_label=label)
            logger.info(f"  Chunk {i + 1} raw LLM response (first 500 chars): "
                        f"{response[:500]}")
            flags = _parse_llm_response(response)
            logger.info(f"  Chunk {i + 1} parsed: {len(flags)} flagged paper(s)")
            if not flags and len(response.strip()) > 5:
                logger.warning(f"  Chunk {i + 1}: LLM returned non-empty response but parser found 0 flags. "
                               f"Response starts with: {response.strip()[:100]!r}")
            raw_flags.extend(flags)
        except Exception as e:
            logger.error(f"LLM session review chunk {i + 1} failed: {e}")

    # Convert raw LLM flags into the frontend-compatible format
    hard_papers: list[dict] = []
    seen_ids: set[str] = set()

    # Build a set of valid session IDs for validation
    valid_sids = set()
    for s in all_sessions:
        sid = s.get("id") or s.get("session_id", "")
        if sid:
            valid_sids.add(sid)

    logger.info(f"  raw_flags count: {len(raw_flags)}, "
                f"first flag keys: {list(raw_flags[0].keys()) if raw_flags else '(empty)'}")
    for flag in raw_flags:
        pid = str(flag.get("paper_id", ""))
        if not pid:
            logger.warning(f"  Skipping flag with empty paper_id: {flag}")
            continue
        if pid in seen_ids:
            logger.debug(f"  Skipping duplicate paper_id: {pid}")
            continue
        seen_ids.add(pid)

        cur_sid = str(flag.get("current_session_id", "")) or paper_session_map.get(pid, "")
        cur_sname = session_name_map.get(cur_sid, cur_sid)

        # Use the LLM's ranked top-5 session suggestions
        top5_raw = flag.get("top5_sessions", [])
        alternatives = []
        for entry in top5_raw[:5]:
            alt_id = str(entry.get("session_id", ""))
            alt_name = entry.get("session_name", "")
            fit_reason = entry.get("fit_reason", "")
            # Validate the session ID exists; use the canonical name if available
            if alt_id in valid_sids:
                canonical_name = session_name_map.get(alt_id, alt_name)
                display_name = canonical_name if canonical_name else alt_name
                if fit_reason:
                    display_name = f"{display_name} — {fit_reason}"
                alternatives.append({
                    "session_id": alt_id,
                    "session_name": display_name,
                })

        # If LLM didn't provide valid top-5, fall back to all sessions
        if not alternatives:
            logger.warning(f"  Paper {pid}: LLM top-5 had no valid session IDs, "
                           f"falling back to full list")
            for s in all_sessions:
                alt_id = s.get("id") or s.get("session_id", "")
                if alt_id and alt_id != cur_sid:
                    alt_name = s.get("sessionName") or s.get("session_name", alt_id)
                    alternatives.append({
                        "session_id": alt_id,
                        "session_name": alt_name,
                    })

        hard_papers.append({
            "paper_id": pid,
            "title": paper_title_map.get(pid, ""),
            "current_session_id": cur_sid,
            "current_session_name": cur_sname,
            "difficultyReason": flag.get("reason", "Flagged by LLM review."),
            "suggestedAction": flag.get("suggested_action", "Review manually."),
            "alternative_sessions": alternatives,
        })

    logger.info(f"LLM session review ({mode}): flagged {len(hard_papers)} "
                f"paper(s) across {len(sessions_data)} sessions")
    return hard_papers
