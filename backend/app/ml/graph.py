"""Road-network graph for the GNN.

Nodes  = road segments (SUMO edges).  A directed edge u -> v exists when a vehicle can drive
from segment u directly onto segment v (SUMO connection).  For message passing we use the
symmetrically normalised adjacency  A_hat = D^-1/2 (A + A^T + I) D^-1/2  so information flows both
upstream (queue spill-back) and downstream (arriving platoons).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch

from app.core.errors import DataValidationError
from app.digital_twin.network import NetworkModel


@dataclass
class GraphSpec:
    node_ids: list[str]
    edge_index: np.ndarray  # [2, E] int64, directed
    free_flow_speed: np.ndarray  # [N] m/s
    length_m: np.ndarray  # [N] metres

    @property
    def n_nodes(self) -> int:
        return len(self.node_ids)

    @classmethod
    def from_network(cls, net: NetworkModel) -> "GraphSpec":
        idx = net.edge_index
        pairs = [(idx[a], idx[b]) for a, b in net.edge_links if a in idx and b in idx]
        ei = np.array(pairs, dtype=np.int64).T if pairs else np.zeros((2, 0), dtype=np.int64)
        return cls(
            node_ids=list(net.edge_ids),
            edge_index=ei,
            free_flow_speed=np.array([e.speed for e in net.edges], dtype=np.float32),
            length_m=np.array([e.length for e in net.edges], dtype=np.float32),
        )

    def validate(self) -> None:
        n = self.n_nodes
        if n == 0:
            raise DataValidationError("Graph has no nodes")
        if self.edge_index.size and (self.edge_index.min() < 0 or self.edge_index.max() >= n):
            raise DataValidationError("Graph edge index refers to unknown nodes")
        if (self.free_flow_speed <= 0).any():
            raise DataValidationError("Free-flow speeds must be positive")


def normalized_adjacency(edge_index: np.ndarray, n: int) -> torch.Tensor:
    a = np.zeros((n, n), dtype=np.float32)
    if edge_index.size:
        a[edge_index[0], edge_index[1]] = 1.0
    a = np.maximum(a, a.T)
    a += np.eye(n, dtype=np.float32)
    d = a.sum(1)
    d_inv_sqrt = 1.0 / np.sqrt(d)
    return torch.from_numpy(a * d_inv_sqrt[:, None] * d_inv_sqrt[None, :])
