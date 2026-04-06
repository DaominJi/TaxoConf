"""
Prompts for context-aware session naming.

Uses the taxonomy hierarchy path, child session names, and paper titles
to generate concise, specific session names in a bottom-up cascade.
A final global normalization pass ensures consistency and uniqueness.
"""

# For leaf sessions: named from taxonomy path + papers only
LEAF_SYSTEM_PROMPT = """\
You are an expert conference program chair. Your task is to generate a
concise, specific session title for a conference oral or poster session."""

LEAF_USER_PROMPT = """\
Generate a session title for the following conference session.

Taxonomy path (from general to specific):
{taxonomy_path}

Papers in this session:
{papers_text}

Requirements:
- The title should be 5-10 words
- More specific than the broadest taxonomy level, but captures all papers
- Suitable as a printed conference program session title
- Do NOT use generic titles like "Miscellaneous" or "Various Topics"

Respond with a JSON object:
{{
  "title": "Your Session Title Here",
  "description": "One sentence describing the session's theme"
}}
"""

# For internal/merged sessions: named from path + child session names + papers
PARENT_SYSTEM_PROMPT = """\
You are an expert conference program chair. Your task is to generate a
concise, specific session title that synthesizes multiple sub-topics into
one coherent session name."""

PARENT_USER_PROMPT = """\
Generate a session title for a conference session that combines papers
from the following sub-topics.

Taxonomy path (from general to specific):
{taxonomy_path}

Child session names already assigned:
{child_sessions_text}

Papers in this session:
{papers_text}

Requirements:
- The title should be 5-10 words
- Broader than any single child session name, but still specific
- Captures the common thread across the sub-topics
- Suitable as a printed conference program session title
- Do NOT just concatenate child session names

Respond with a JSON object:
{{
  "title": "Your Session Title Here",
  "description": "One sentence describing the session's theme"
}}
"""

# Global normalization pass: ensure consistency and uniqueness across all sessions
NORMALIZE_SYSTEM_PROMPT = """\
You are an expert conference program chair finalizing the session titles \
for a conference program. Your task is to review ALL session names together \
and ensure they are consistent, distinct, and professional."""

NORMALIZE_USER_PROMPT = """\
Below are all the session titles for this conference. Review them as a \
complete set and revise any that need improvement.

{sessions_text}

Rules:
- Fix any sessions with GENERIC names like "All Papers", "Miscellaneous", \
"Various Topics", "General Session", or "Other" — replace them with a \
specific title based on their papers listed below.
- Fix any sessions with DUPLICATE or near-duplicate names — make them \
distinct by highlighting what differentiates each session.
- Ensure CONSISTENT style: all titles should be noun phrases of 5-10 \
words, no verbs, no "Session on..." prefix.
- Keep names that are already good — do NOT change them unnecessarily.
- Every session must have a unique, specific title.

{problematic_sessions_text}

Respond with a JSON object mapping session IDs to revised titles. \
Include ALL sessions, even unchanged ones:
{{
  "session_id_1": "Revised or Original Title",
  "session_id_2": "Revised or Original Title",
  ...
}}

Respond ONLY with the JSON object, no other text."""
