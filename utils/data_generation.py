import bnlearn as bn
import networkx as nx
import numpy as np
import os
import pprint
import sys

pp = pprint.PrettyPrinter(width=82, compact=True)

# Utility functions to mute printing done in BNLearn
class HiddenPrints:
    def __enter__(self):
        self._original_stdout = sys.stdout
        sys.stdout = open(os.devnull, 'w')

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout.close()
        sys.stdout = self._original_stdout

def generate_dataset(bn_path, n=10000, seed=42):
    # XXX: unfortunately, there is no better way to control randomness in bn.sampling
    np.random.seed(seed)
    
    # Load DAG, probability tables, etc.
    with HiddenPrints():
        model = bn.import_DAG(bn_path, verbose=1)

    G = nx.from_pandas_adjacency(model["adjmat"].astype(int), create_using=nx.DiGraph)
    
    # Sample data
    data = bn.sampling(model, n=n, verbose=1)
    
    # Label nodes in causal graph
    nx.relabel_nodes(G, dict(zip(range(len(G.nodes())), data.columns)))
    
    return G, data