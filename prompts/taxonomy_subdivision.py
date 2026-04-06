"""
Prompts for taxonomy node subdivision.

The LLM proposes child sub-categories for a given set of papers.
"""

SYSTEM_PROMPT = """\
You are an expert conference program chair organizing an academic conference.
Your task is to propose topically coherent sub-categories for a given set of
research papers. Each sub-category should be specific enough to form a
meaningful conference session, but broad enough to contain multiple papers.
"""

USER_PROMPT = """\
I have a set of papers under the topic: "{node_name}"
Description: {node_description}

Here are the papers:
{papers_text}

Based on these papers, propose sub-categories that partition them into
coherent topical groups. Each sub-category should:
- Have a clear, concise name suitable as a conference session title
- Have a brief description (1-2 sentences)
- Be distinct from other sub-categories
- Cover at least {min_papers} papers

If the papers are already homogeneous enough that further subdivision would
be artificial (i.e., they naturally form a single coherent session), respond
with exactly: {{"status": "CANNOT_SPLIT"}}

Otherwise, respond with a JSON object:
{{
  "status": "OK",
  "categories": [
    {{
      "name": "Category Name",
      "description": "Brief description of what this category covers"
    }},
    ...
  ]
}}

Important:
- Propose at most {max_children} categories.
- Every paper should fit into exactly one category.
- Respond ONLY with the JSON object, no other text.
"""
