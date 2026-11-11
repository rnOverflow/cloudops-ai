"""Runbook loading and BM25 retrieval.

BM25 is used instead of embeddings: the corpus is small, the vocabulary is operational
jargon that lexical matching handles well, results are explainable, and it needs no
model or external API. The interface allows swapping in a vector index later."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "in",
    "on",
    "for",
    "is",
    "are",
    "be",
    "with",
    "if",
    "it",
    "its",
    "this",
    "that",
    "by",
    "at",
    "as",
    "from",
}


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


@dataclass
class RunbookDoc:
    slug: str
    title: str
    severity: str
    tags: list[str]
    symptoms: list[str]
    actions: list[str]
    summary: str
    content: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "title": self.title,
            "severity": self.severity,
            "tags": self.tags,
            "symptoms": self.symptoms,
            "actions": self.actions,
            "summary": self.summary,
        }


def parse_runbook(path: Path) -> RunbookDoc:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{path.name}: missing front matter")
    _, fm, body = text.split("---", 2)
    meta = yaml.safe_load(fm) or {}
    for key in ("slug", "title", "actions"):
        if key not in meta:
            raise ValueError(f"{path.name}: front matter missing '{key}'")
    return RunbookDoc(
        slug=meta["slug"],
        title=meta["title"],
        severity=meta.get("severity", "MEDIUM"),
        tags=list(meta.get("tags", [])),
        symptoms=list(meta.get("symptoms", [])),
        actions=list(meta["actions"]),
        summary=meta.get("summary", ""),
        content=body.strip(),
    )


def load_runbooks(directory: Path) -> list[RunbookDoc]:
    return [parse_runbook(p) for p in sorted(directory.glob("*.md"))]


@dataclass
class BM25Index:
    docs: list[RunbookDoc]
    k1: float = 1.5
    b: float = 0.75
    _tf: list[Counter[str]] = field(default_factory=list)
    _len: list[int] = field(default_factory=list)
    _idf: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        df: Counter[str] = Counter()
        for d in self.docs:
            # Title, tags and symptoms are weighted by repetition (field boosting).
            tokens = (
                tokenize(d.title) * 3
                + tokenize(" ".join(d.tags)) * 3
                + tokenize(" ".join(d.symptoms)) * 2
                + tokenize(d.summary)
                + tokenize(d.content)
            )
            tf = Counter(tokens)
            self._tf.append(tf)
            self._len.append(len(tokens))
            df.update(tf.keys())
        n = len(self.docs)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self._avg = (sum(self._len) / n) if n else 0

    def search(self, query: str, limit: int = 3) -> list[tuple[RunbookDoc, float]]:
        q = tokenize(query)
        scored = []
        for i, d in enumerate(self.docs):
            tf, dl = self._tf[i], self._len[i]
            score = 0.0
            for t in q:
                if t not in tf:
                    continue
                f = tf[t]
                score += (
                    self._idf.get(t, 0)
                    * f
                    * (self.k1 + 1)
                    / (f + self.k1 * (1 - self.b + self.b * dl / self._avg))
                )
            if score > 0:
                scored.append((d, round(score, 3)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]
