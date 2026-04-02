"""
Floor plan optimizer for poster sessions.

Given a set of papers and a physical layout, assigns papers to board
positions such that topically similar papers are placed near each other.

Supported layouts:
  - LINE:      Boards in a single row. Adjacent boards = similar topics.
  - CIRCLE:    Boards around a circle. When right-priority is enabled,
               the layout optimizes for a left-to-right walking direction:
               the right-side (next) neighbor of each board is prioritized
               to be more similar, so topics transition smoothly as you walk
               clockwise. Uses a directional cost function with multi-hop
               forward lookahead weights.
  - RECTANGLE: Boards in a grid (R rows × C cols). Papers within a row
               are similar; adjacent rows also share thematic proximity.

Algorithms:
  - LINE:      Solve a TSP (nearest-neighbor + 2-opt).
  - CIRCLE:    Standard circular TSP + direction selection + directional
               local search (adjacent swaps, Or-opt) with asymmetric cost.
  - RECTANGLE: First cluster papers into rows (spectral/greedy),
               then order within each row (TSP), then order rows
               so adjacent rows are topically close.
"""
import logging
import math
from typing import Optional

import numpy as np

import config
from models import Paper, BoardPosition, PosterAssignment, FloorPlanType

logger = logging.getLogger(__name__)


class FloorPlanOptimizer:
    """Assigns papers to poster board positions for maximum proximity coherence."""

    def __init__(self, sim_matrix: np.ndarray, paper_ids: list[str],
                 floor_plan: FloorPlanType = None, rect_cols: int = None):
        """
        Args:
            sim_matrix: N×N similarity matrix (higher = more similar).
            paper_ids:  Ordered list of paper IDs matching sim_matrix.
            floor_plan: Layout type (LINE, CIRCLE, RECTANGLE).
            rect_cols:  Number of columns per row (RECTANGLE only).
        """
        self.sim = sim_matrix
        self.paper_ids = paper_ids
        self.n = len(paper_ids)
        self.floor_plan = floor_plan or FloorPlanType(config.POSTER_FLOOR_PLAN)
        self.rect_cols = rect_cols or config.POSTER_RECT_COLS

        # Convert similarity to distance (for TSP-like problems)
        # distance = 1 - similarity (similarity is cosine in [0,1])
        self.dist = 1.0 - np.clip(sim_matrix, 0, 1)

    def optimize(self) -> list[PosterAssignment]:
        """Run the layout optimizer and return board assignments."""
        if self.n == 0:
            return []

        extra = ""
        if (self.floor_plan == FloorPlanType.CIRCLE
                and config.CIRCLE_RIGHT_PRIORITY):
            extra = " (right-priority enabled)"
        logger.info(f"Optimizing {self.floor_plan.value} layout for "
                     f"{self.n} papers{extra}")

        if self.floor_plan == FloorPlanType.LINE:
            order = self._solve_line()
            assignments = self._build_line_assignments(order)
        elif self.floor_plan == FloorPlanType.CIRCLE:
            order = self._solve_circle()
            assignments = self._build_circle_assignments(order)
        elif self.floor_plan == FloorPlanType.RECTANGLE:
            grid = self._solve_rectangle()
            assignments = self._build_rect_assignments(grid)
        else:
            raise ValueError(f"Unknown floor plan: {self.floor_plan}")

        score = self._evaluate_proximity(assignments)
        logger.info(f"  Layout score (avg neighbor similarity): {score:.4f}")
        return assignments

    # ═══════════════════════════════════════════════════════════════
    # LINE layout: 1D TSP
    # ═══════════════════════════════════════════════════════════════

    def _solve_line(self) -> list[int]:
        """Solve the linear arrangement: order indices for max adjacent similarity."""
        order = self._tsp_nearest_neighbor(circular=False)
        order = self._tsp_2opt(order, circular=False)
        return order

    def _build_line_assignments(self, order: list[int]) -> list[PosterAssignment]:
        """Build assignments from a linear ordering."""
        assignments = []
        for pos, idx in enumerate(order):
            board = BoardPosition(index=pos, row=0, col=pos)
            assignments.append(PosterAssignment(
                paper_id=self.paper_ids[idx], board=board))
        return assignments

    # ═══════════════════════════════════════════════════════════════
    # CIRCLE layout: directional circular TSP (right-priority)
    # ═══════════════════════════════════════════════════════════════

    def _solve_circle(self) -> list[int]:
        """
        Solve the circular arrangement with right-side priority.

        When CIRCLE_RIGHT_PRIORITY is enabled, people are assumed to walk
        left-to-right (clockwise). The optimization uses a directional cost
        function that weights forward (right) neighbors more heavily than
        backward (left) neighbors, including multi-hop lookahead:

            cost(tour) = sum_i [ w1 * dist(tour[i], tour[i+1])
                               + w2 * dist(tour[i], tour[i+2])
                               + ... ]

        This is genuinely asymmetric in tour direction because only forward
        hops are counted. Reversing the tour changes the cost.

        Algorithm:
          1. Solve regular circular TSP (nearest-neighbor + 2-opt)
          2. Evaluate directional cost for both clockwise and counterclockwise
          3. Pick the better direction
          4. Apply directional local search (adjacent swaps evaluated with
             the asymmetric cost function) to further improve right-side flow
        """
        # Step 1: Standard circular TSP for good initial ordering
        order = self._tsp_nearest_neighbor(circular=True)
        order = self._tsp_2opt(order, circular=True)

        if not config.CIRCLE_RIGHT_PRIORITY or self.n < 4:
            return order

        # Step 2: Compare both traversal directions
        cost_fwd = self._directional_tour_cost(order)
        cost_rev = self._directional_tour_cost(list(reversed(order)))

        if cost_rev < cost_fwd:
            order = list(reversed(order))
            logger.info(f"  Circle: reversed direction (cost {cost_fwd:.4f} → {cost_rev:.4f})")

        # Step 3: Directional local search refinement
        order = self._directional_local_search(order)

        return order

    def _directional_tour_cost(self, tour: list[int]) -> float:
        """
        Compute the directional cost of a circular tour.

        Only forward (right-side) hops contribute to the cost, weighted
        by CIRCLE_FORWARD_WEIGHTS. This makes the cost genuinely asymmetric:
        reversing the tour produces a different cost because different papers
        end up as 1st-right vs 2nd-right neighbors.

            cost = sum_{i} sum_{k=1}^{K} w_k * dist[tour[i], tour[(i+k) % n]]

        where K = len(CIRCLE_FORWARD_WEIGHTS) and w_k = weights[k-1].
        """
        n = len(tour)
        if n < 2:
            return 0.0

        weights = config.CIRCLE_FORWARD_WEIGHTS
        total = 0.0
        for i in range(n):
            for k, w in enumerate(weights, start=1):
                if k >= n:
                    break
                j = (i + k) % n
                total += w * self.dist[tour[i], tour[j]]
        return total

    def _directional_local_search(self, tour: list[int],
                                   max_passes: int = 50) -> list[int]:
        """
        Directional local search: improve the tour by swapping adjacent
        papers when it reduces the directional cost.

        Moves considered:
          1. Adjacent swap: swap tour[i] and tour[i+1]
          2. Block rotation: shift a block of 3 papers one position right
          3. Or-opt: relocate a single paper to a better position

        All moves are evaluated using the asymmetric directional cost.
        """
        tour = list(tour)
        n = len(tour)
        if n < 4:
            return tour

        best_cost = self._directional_tour_cost(tour)

        for pass_num in range(max_passes):
            improved = False

            # Try adjacent swaps
            for i in range(n):
                j = (i + 1) % n
                # Swap positions i and j
                tour[i], tour[j] = tour[j], tour[i]
                new_cost = self._directional_tour_cost(tour)
                if new_cost < best_cost - 1e-10:
                    best_cost = new_cost
                    improved = True
                else:
                    # Revert
                    tour[i], tour[j] = tour[j], tour[i]

            # Try Or-opt: relocate each paper to each other position
            for i in range(n):
                paper = tour[i]
                remaining = tour[:i] + tour[i+1:]
                for j in range(len(remaining) + 1):
                    candidate = remaining[:j] + [paper] + remaining[j:]
                    new_cost = self._directional_tour_cost(candidate)
                    if new_cost < best_cost - 1e-10:
                        tour = candidate
                        best_cost = new_cost
                        improved = True
                        break
                # Tour may have changed, re-derive n and indices
                n = len(tour)

            if not improved:
                break

        logger.info(f"  Circle directional search: {pass_num + 1} passes, "
                     f"final cost: {best_cost:.4f}")
        return tour

    def _build_circle_assignments(self, order: list[int]) -> list[PosterAssignment]:
        """Build assignments with angular positions around a circle."""
        assignments = []
        angle_step = 360.0 / max(len(order), 1)
        for pos, idx in enumerate(order):
            angle = pos * angle_step
            board = BoardPosition(index=pos, angle=angle)
            assignments.append(PosterAssignment(
                paper_id=self.paper_ids[idx], board=board))
        return assignments

    # ═══════════════════════════════════════════════════════════════
    # RECTANGLE layout: 2D grid
    # ═══════════════════════════════════════════════════════════════

    def _solve_rectangle(self) -> list[list[int]]:
        """
        Solve the rectangular arrangement:
          1. Partition papers into rows (clusters of size ~rect_cols).
          2. Order papers within each row for intra-row coherence.
          3. Order rows so adjacent rows are thematically close.

        Returns a list of rows, each a list of paper indices.
        """
        num_rows = math.ceil(self.n / self.rect_cols)
        logger.info(f"  Rectangle: {num_rows} rows × {self.rect_cols} cols")

        # Step 1: Partition into rows using greedy cluster packing
        rows = self._partition_into_rows(num_rows)

        # Step 2: Order papers within each row (mini-TSP per row)
        for i in range(len(rows)):
            if len(rows[i]) > 2:
                rows[i] = self._order_within_row(rows[i])

        # Step 3: Order the rows themselves so adjacent rows are similar
        rows = self._order_rows(rows)

        return rows

    def _partition_into_rows(self, num_rows: int) -> list[list[int]]:
        """
        Partition N papers into num_rows groups of roughly equal size,
        maximizing intra-group similarity.

        Uses a spectral-like approach: compute the Fiedler vector (second
        smallest eigenvector of the Laplacian) of the similarity graph,
        sort by it, then cut into roughly equal chunks. This naturally
        groups similar papers together.
        """
        if self.n <= self.rect_cols:
            return [list(range(self.n))]

        # Build Laplacian from similarity
        W = np.copy(self.sim)
        np.fill_diagonal(W, 0)
        D = np.diag(W.sum(axis=1))
        L = D - W

        try:
            eigenvalues, eigenvectors = np.linalg.eigh(L)
            # Fiedler vector is the 2nd smallest eigenvector
            fiedler = eigenvectors[:, 1]
            # Sort papers by Fiedler value
            sorted_indices = np.argsort(fiedler).tolist()
        except np.linalg.LinAlgError:
            # Fallback to random ordering
            logger.warning("  Eigendecomposition failed, using index order")
            sorted_indices = list(range(self.n))

        # Cut into roughly equal-sized rows
        rows = []
        chunk_size = self.rect_cols
        for i in range(0, len(sorted_indices), chunk_size):
            chunk = sorted_indices[i:i + chunk_size]
            rows.append(chunk)

        return rows

    def _order_within_row(self, indices: list[int]) -> list[int]:
        """Order papers within a single row using nearest-neighbor heuristic."""
        if len(indices) <= 2:
            return indices

        # Extract sub-distance matrix
        sub_dist = self.dist[np.ix_(indices, indices)]
        n = len(indices)

        # Nearest-neighbor starting from the paper most central to the group
        centrality = sub_dist.sum(axis=1)
        start = int(np.argmin(centrality))

        visited = [start]
        unvisited = set(range(n)) - {start}
        while unvisited:
            last = visited[-1]
            nearest = min(unvisited, key=lambda j: sub_dist[last, j])
            visited.append(nearest)
            unvisited.discard(nearest)

        # Apply 2-opt improvement on the sub-problem
        visited = self._2opt_on_sublist(visited, sub_dist, circular=False)

        return [indices[i] for i in visited]

    def _order_rows(self, rows: list[list[int]]) -> list[list[int]]:
        """
        Order the rows so that adjacent rows have high inter-row similarity.
        Compute a row-level similarity matrix (average pairwise similarity
        between papers of two rows), then solve a 1D TSP on rows.
        """
        if len(rows) <= 2:
            return rows

        nr = len(rows)
        row_sim = np.zeros((nr, nr))
        for i in range(nr):
            for j in range(i + 1, nr):
                # Average similarity between papers in row i and row j
                pairs = [(a, b) for a in rows[i] for b in rows[j]]
                if pairs:
                    avg = np.mean([self.sim[a, b] for a, b in pairs])
                else:
                    avg = 0.0
                row_sim[i, j] = avg
                row_sim[j, i] = avg

        row_dist = 1.0 - np.clip(row_sim, 0, 1)

        # Nearest-neighbor TSP on rows
        start = 0
        visited = [start]
        unvisited = set(range(nr)) - {start}
        while unvisited:
            last = visited[-1]
            nearest = min(unvisited, key=lambda j: row_dist[last, j])
            visited.append(nearest)
            unvisited.discard(nearest)

        visited = self._2opt_on_sublist(visited, row_dist, circular=False)
        return [rows[i] for i in visited]

    def _build_rect_assignments(self, grid: list[list[int]]) -> list[PosterAssignment]:
        """Build assignments from a 2D grid."""
        assignments = []
        global_idx = 0
        for row_num, row in enumerate(grid):
            for col_num, paper_idx in enumerate(row):
                board = BoardPosition(
                    index=global_idx, row=row_num, col=col_num)
                assignments.append(PosterAssignment(
                    paper_id=self.paper_ids[paper_idx], board=board))
                global_idx += 1
        return assignments

    # ═══════════════════════════════════════════════════════════════
    # TSP Heuristics
    # ═══════════════════════════════════════════════════════════════

    def _tsp_nearest_neighbor(self, circular: bool = False) -> list[int]:
        """
        Greedy nearest-neighbor TSP heuristic.
        Start from the most "central" paper (smallest total distance).
        """
        total_dist = self.dist.sum(axis=1)
        start = int(np.argmin(total_dist))

        tour = [start]
        unvisited = set(range(self.n)) - {start}

        while unvisited:
            last = tour[-1]
            nearest = min(unvisited, key=lambda j: self.dist[last, j])
            tour.append(nearest)
            unvisited.discard(nearest)

        return tour

    def _tsp_2opt(self, tour: list[int], circular: bool = False,
                  max_iterations: int = 1000) -> list[int]:
        """Improve a tour using the 2-opt local search."""
        return self._2opt_on_sublist(tour, self.dist, circular, max_iterations)

    @staticmethod
    def _2opt_on_sublist(tour: list[int], dist: np.ndarray,
                         circular: bool = False,
                         max_iterations: int = 1000) -> list[int]:
        """Generic 2-opt improvement."""
        n = len(tour)
        if n <= 3:
            return tour

        tour = list(tour)
        improved = True
        iteration = 0

        while improved and iteration < max_iterations:
            improved = False
            iteration += 1
            for i in range(n - 1):
                for j in range(i + 2, n):
                    if not circular and j == n - 1 and i == 0:
                        continue  # Skip reversing entire tour for open path

                    # Current cost of edges (i, i+1) and (j, j+1 mod n)
                    a, b = tour[i], tour[i + 1]
                    if circular:
                        c, d = tour[j], tour[(j + 1) % n]
                    else:
                        if j + 1 < n:
                            c, d = tour[j], tour[j + 1]
                        else:
                            # For open path, only consider the (j-1, j) edge
                            c, d = tour[j], tour[j]

                    old_cost = dist[a, b] + dist[c, d]
                    new_cost = dist[a, c] + dist[b, d]

                    if new_cost < old_cost - 1e-10:
                        # Reverse the segment between i+1 and j
                        tour[i + 1:j + 1] = tour[i + 1:j + 1][::-1]
                        improved = True

        return tour

    # ═══════════════════════════════════════════════════════════════
    # Evaluation
    # ═══════════════════════════════════════════════════════════════

    def _evaluate_proximity(self, assignments: list[PosterAssignment]) -> float:
        """
        Evaluate the quality of a layout by computing the average similarity
        between physically adjacent papers.

        For CIRCLE with right-priority: reports the weighted right-side score
        using the directional cost function (lower is better for cost, but we
        report as similarity which is higher-is-better).
        """
        if len(assignments) < 2:
            return 0.0

        pid_to_idx = {pid: i for i, pid in enumerate(self.paper_ids)}

        # For circle with right-priority, use the directional metric
        if (self.floor_plan == FloorPlanType.CIRCLE
                and config.CIRCLE_RIGHT_PRIORITY and self.n >= 4):
            return self._evaluate_circle_directional(assignments, pid_to_idx)

        neighbors = self._get_neighbor_pairs(assignments)
        if not neighbors:
            return 0.0

        total_sim = 0.0
        for pid_a, pid_b in neighbors:
            ia = pid_to_idx.get(pid_a)
            ib = pid_to_idx.get(pid_b)
            if ia is not None and ib is not None:
                total_sim += self.sim[ia, ib]

        return total_sim / len(neighbors)

    def _evaluate_circle_directional(self, assignments: list[PosterAssignment],
                                      pid_to_idx: dict[str, int]) -> float:
        """
        Evaluate circle layout using the directional (right-priority) metric.

        Returns the weighted average right-side similarity:
            score = sum_i sum_k w_k * sim[tour[i], tour[(i+k)%n]] / (n * sum(w))

        Higher is better. Reports how smoothly topics transition when walking
        left-to-right around the circle.
        """
        sorted_a = sorted(assignments, key=lambda a: a.board.index)
        n = len(sorted_a)
        weights = config.CIRCLE_FORWARD_WEIGHTS

        total_sim = 0.0
        total_weight = 0.0
        for i in range(n):
            ia = pid_to_idx.get(sorted_a[i].paper_id)
            if ia is None:
                continue
            for k, w in enumerate(weights, start=1):
                if k >= n:
                    break
                j = (i + k) % n
                ib = pid_to_idx.get(sorted_a[j].paper_id)
                if ib is not None:
                    total_sim += w * self.sim[ia, ib]
                    total_weight += w

        return total_sim / total_weight if total_weight > 0 else 0.0

    def _get_neighbor_pairs(self, assignments: list[PosterAssignment]) \
            -> list[tuple[str, str]]:
        """Get all pairs of papers that are physically adjacent."""
        pairs = []

        if self.floor_plan == FloorPlanType.LINE:
            sorted_a = sorted(assignments, key=lambda a: a.board.index)
            for i in range(len(sorted_a) - 1):
                pairs.append((sorted_a[i].paper_id, sorted_a[i + 1].paper_id))

        elif self.floor_plan == FloorPlanType.CIRCLE:
            sorted_a = sorted(assignments, key=lambda a: a.board.index)
            for i in range(len(sorted_a)):
                j = (i + 1) % len(sorted_a)
                pairs.append((sorted_a[i].paper_id, sorted_a[j].paper_id))

        elif self.floor_plan == FloorPlanType.RECTANGLE:
            # Build a grid lookup
            grid: dict[tuple[int, int], str] = {}
            for a in assignments:
                if a.board.row is not None and a.board.col is not None:
                    grid[(a.board.row, a.board.col)] = a.paper_id

            for (r, c), pid in grid.items():
                # Right neighbor
                if (r, c + 1) in grid:
                    pairs.append((pid, grid[(r, c + 1)]))
                # Below neighbor
                if (r + 1, c) in grid:
                    pairs.append((pid, grid[(r + 1, c)]))

        return pairs


# ─── Convenience function ────────────────────────────────────────

def compute_layout(paper_ids: list[str], sim_matrix: np.ndarray,
                   floor_plan: FloorPlanType, rect_cols: int = None
                   ) -> list[PosterAssignment]:
    """
    Convenience wrapper: compute an optimized layout for given papers.
    """
    optimizer = FloorPlanOptimizer(
        sim_matrix=sim_matrix,
        paper_ids=paper_ids,
        floor_plan=floor_plan,
        rect_cols=rect_cols,
    )
    return optimizer.optimize()
