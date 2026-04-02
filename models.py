"""
Data models for the session organizer (oral + poster).
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


@dataclass
class Paper:
    """A conference paper."""
    id: str
    title: str
    abstract: str
    authors: list[str]

    def author_set(self) -> set[str]:
        return {a.strip().lower() for a in self.authors}

    def text_for_embedding(self) -> str:
        """Combined text for similarity computation."""
        return f"{self.title}. {self.abstract}"


class FloorPlanType(Enum):
    LINE = "line"
    CIRCLE = "circle"
    RECTANGLE = "rectangle"


@dataclass
class TaxonomyNode:
    """A node in the LLM-generated topic taxonomy."""
    node_id: str
    name: str
    description: str
    parent_id: Optional[str] = None
    children: list["TaxonomyNode"] = field(default_factory=list)
    paper_ids: list[str] = field(default_factory=list)
    is_leaf: bool = True
    depth: int = 0

    def __repr__(self):
        return (f"TaxonomyNode(id={self.node_id}, name='{self.name}', "
                f"depth={self.depth}, #papers={len(self.paper_ids)}, "
                f"is_leaf={self.is_leaf}, #children={len(self.children)})")


@dataclass
class Session:
    """An oral presentation session."""
    session_id: str
    name: str
    description: str
    paper_ids: list[str] = field(default_factory=list)
    taxonomy_node_id: Optional[str] = None
    time_slot: Optional[int] = None
    track: Optional[int] = None

    def author_set(self, papers_map: dict[str, Paper]) -> set[str]:
        authors = set()
        for pid in self.paper_ids:
            if pid in papers_map:
                authors |= papers_map[pid].author_set()
        return authors

    def __repr__(self):
        return (f"Session(id={self.session_id}, name='{self.name}', "
                f"#papers={len(self.paper_ids)}, slot={self.time_slot}, "
                f"track={self.track})")


@dataclass
class BoardPosition:
    """Physical position of a poster board."""
    index: int                  # Global board index within the session
    row: Optional[int] = None  # Row in rectangle layout (0-indexed)
    col: Optional[int] = None  # Column in rectangle layout (0-indexed)
    angle: Optional[float] = None  # Angle in circle layout (degrees)

    def __repr__(self):
        if self.row is not None:
            return f"Board(idx={self.index}, row={self.row}, col={self.col})"
        elif self.angle is not None:
            return f"Board(idx={self.index}, angle={self.angle:.0f}°)"
        return f"Board(idx={self.index})"


@dataclass
class PosterAssignment:
    """A paper assigned to a specific poster board."""
    paper_id: str
    board: BoardPosition


@dataclass
class PosterSession:
    """A poster session with physical board layout."""
    session_id: str
    name: str
    description: str
    time_slot: Optional[int] = None
    area: Optional[int] = None          # Parallel poster area (0-indexed)
    assignments: list[PosterAssignment] = field(default_factory=list)
    taxonomy_node_ids: list[str] = field(default_factory=list)
    floor_plan: FloorPlanType = FloorPlanType.LINE

    @property
    def paper_ids(self) -> list[str]:
        return [a.paper_id for a in self.assignments]

    def author_set(self, papers_map: dict[str, Paper]) -> set[str]:
        authors = set()
        for a in self.assignments:
            if a.paper_id in papers_map:
                authors |= papers_map[a.paper_id].author_set()
        return authors

    def __repr__(self):
        return (f"PosterSession(id={self.session_id}, name='{self.name}', "
                f"#papers={len(self.assignments)}, slot={self.time_slot}, "
                f"area={self.area}, layout={self.floor_plan.value})")
