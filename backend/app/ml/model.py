"""Spatio-temporal GNN for congestion forecasting.

Architecture (documented in docs/GNN.md):
  per time step   : 2 x graph convolution (Kipf & Welling GCN, dense normalised adjacency)
  over time       : GRU per road segment on the sequence of spatial embeddings
  output          : MLP head predicting the *change* of CI between the last observed interval and
                    the interval ``horizon`` steps ahead  ->  prediction = CI_last + delta (clipped to [0,1])
PyTorch Geometric is intentionally not required: a dense GCN on a few dozen nodes is equivalent to
``GCNConv`` and removes an installation risk on Windows.
"""
from __future__ import annotations

import torch
from torch import nn


class GraphConv(nn.Module):
    def __init__(self, d_in: int, d_out: int) -> None:
        super().__init__()
        self.lin = nn.Linear(d_in, d_out)

    def forward(self, x: torch.Tensor, a_hat: torch.Tensor) -> torch.Tensor:
        # x: [..., N, F]  a_hat: [N, N]
        return torch.matmul(a_hat, self.lin(x))


class TrafficGNN(nn.Module):
    def __init__(self, n_dynamic: int, n_static: int, hidden: int = 32, dropout: float = 0.1) -> None:
        super().__init__()
        self.n_static = n_static
        d_in = n_dynamic + n_static
        self.gc1 = GraphConv(d_in, hidden)
        self.gc2 = GraphConv(hidden, hidden)
        self.gru = nn.GRU(hidden, hidden, batch_first=True)
        self.drop = nn.Dropout(dropout)
        self.head = nn.Sequential(nn.Linear(hidden + 1, hidden), nn.ReLU(), nn.Linear(hidden, 1))

    def forward(
        self, x: torch.Tensor, static: torch.Tensor, a_hat: torch.Tensor, ci_last: torch.Tensor
    ) -> torch.Tensor:
        """x [B,W,N,F_dyn] (scaled), static [N,F_static], ci_last [B,N] -> prediction [B,N]."""
        b, w, n, _ = x.shape
        s = static.unsqueeze(0).unsqueeze(0).expand(b, w, n, static.shape[-1])
        h = torch.relu(self.gc1(torch.cat([x, s], dim=-1), a_hat))
        h = self.drop(h)
        h = torch.relu(self.gc2(h, a_hat))  # [B,W,N,H]
        h = h.permute(0, 2, 1, 3).reshape(b * n, w, -1)
        _, last = self.gru(h)  # [1, B*N, H]
        z = torch.cat([last[0].reshape(b, n, -1), ci_last.unsqueeze(-1)], dim=-1)
        delta = self.head(z).squeeze(-1)
        return ci_last + delta
