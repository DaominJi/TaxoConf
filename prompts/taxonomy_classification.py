"""
Prompts for paper classification into taxonomy categories.

The LLM assigns each paper to exactly one of the proposed child categories.
"""

SYSTEM_PROMPT = """\
You are an expert at categorizing academic papers into topical categories.
You must assign each paper to exactly one category based on its content.
"""

USER_PROMPT = """\
Classify each of the following papers into exactly one of the given categories.

Categories:
{categories_text}

Papers:
{papers_text}

Respond with a JSON object mapping paper IDs to category names:
{{
  "paper_id_1": "Category Name",
  "paper_id_2": "Category Name",
  ...
}}

Rules:
- Every paper must be assigned to exactly one category.
- Use the exact category names as provided above.
- If a paper fits multiple categories, choose the best fit.
- Respond ONLY with the JSON object, no other text.
"""
