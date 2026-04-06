"""
Prompts for context-aware session naming.

Uses the taxonomy hierarchy path, child session names, and paper titles
to generate concise, specific session names in a bottom-up cascade.
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
