"""
Prompts for LLM-based session review (hard paper flagging).

The LLM reviews organized sessions and identifies misplaced papers.
"""

SYSTEM_PROMPT = """\
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

USER_PROMPT = """\
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
