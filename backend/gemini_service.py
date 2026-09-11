"""
gemini_service.py
Thin wrapper around Google's Gemini API (google-genai SDK). Provides two
AI-powered features for the expense tracker:

1. parse_expense_text(text, categories) -> structured expense fields from
   a natural-language sentence like "Spent 450 on groceries yesterday".
2. generate_insights(summary) -> a short list of personalized spending
   insights/tips based on the user's aggregated expense data.

If no API key is configured, both functions raise GeminiNotConfigured so
the Flask layer can return a clean, actionable error instead of crashing.
"""

import os
import json
import re
from datetime import date

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


class GeminiNotConfigured(Exception):
    """Raised when GEMINI_API_KEY is missing so the caller can respond gracefully."""
    pass


def _get_client():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise GeminiNotConfigured(
            "GEMINI_API_KEY is not set. Add it to backend/.env to enable AI features."
        )
    from google import genai  # imported lazily so the app still runs without the package configured
    return genai.Client(api_key=api_key)


def _extract_json(text):
    """Best-effort extraction of a JSON object/array from a model response."""
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if match:
        text = match.group(1)
    return json.loads(text)


def parse_expense_text(text, category_names):
    """
    Turn a free-form sentence into structured expense fields.
    Returns a dict: { amount, category, description, date, payment_method }
    `category` is guaranteed to be one of category_names (falls back to 'Other').
    """
    client = _get_client()
    today = date.today().isoformat()
    category_list = ", ".join(category_names)

    prompt = f"""You extract structured expense data from a short piece of text written by a user of a personal expense tracker.

Today's date is {today}.
Valid categories (choose the single best match, or "Other" if nothing fits): {category_list}

Text: "{text}"

Respond with ONLY a JSON object, no markdown, no explanation, in exactly this shape:
{{
  "amount": <number, the numeric amount spent, no currency symbol>,
  "category": "<one of the valid categories exactly as written>",
  "description": "<a short 2-6 word description of what the expense was for>",
  "date": "<YYYY-MM-DD, resolve relative terms like 'today', 'yesterday', weekday names relative to today's date>",
  "payment_method": "<one of: Cash, Card, UPI, Bank Transfer, Other — infer if mentioned, otherwise 'Cash'>"
}}

If you cannot find a numeric amount, set "amount" to 0."""

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config={"response_mime_type": "application/json", "temperature": 0.1},
    )

    data = _extract_json(response.text)

    if data.get("category") not in category_names:
        data["category"] = "Other"
    try:
        data["amount"] = round(float(data.get("amount", 0)), 2)
    except (TypeError, ValueError):
        data["amount"] = 0
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(data.get("date", ""))):
        data["date"] = today
    data["description"] = str(data.get("description", "")).strip()[:120]
    if data.get("payment_method") not in ("Cash", "Card", "UPI", "Bank Transfer", "Other"):
        data["payment_method"] = "Cash"

    return data


def generate_insights(summary):
    """
    Given an aggregated summary dict of the user's spending, ask Gemini for
    a short list of concrete, personalized insights and money-saving tips.
    Returns a list of plain-text strings.
    """
    client = _get_client()

    prompt = f"""You are a friendly personal finance assistant inside an expense tracker app.
Here is a JSON summary of the user's recent spending:

{json.dumps(summary, indent=2)}

Based on this data, write 3 to 5 short, specific, and actionable insights or
money-saving tips. Reference actual numbers/categories from the data where
relevant. Keep each insight to one sentence, no more than 25 words.

Respond with ONLY a JSON array of strings, no markdown, no explanation. Example:
["insight one", "insight two", "insight three"]"""

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config={"response_mime_type": "application/json", "temperature": 0.4},
    )

    data = _extract_json(response.text)
    if isinstance(data, dict):
        data = data.get("insights", [])
    return [str(item) for item in data][:5]
