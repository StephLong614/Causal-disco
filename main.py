import argparse

from causaldag import DAG

import networkx as nx
import os
import pandas as pd
import wandb
import numpy as np
import random

from algo.greedy_search import greedy_search_mec_size, greedy_search_confidence, greedy_search_bic

from models.noisy_expert import NoisyExpert
from models.oracles import EpsilonOracle

from utils.data_generation import generate_dataset
from utils.plotting import plot_heatmap
from utils.dag_utils import get_undirected_edges, is_dag_in_mec
from utils.metrics import get_mec_shd
from utils.language_models import get_lms_probs, calibrate

parser = argparse.ArgumentParser(description='Description of your program.')

# Add arguments
parser.add_argument('--algo', default="greedy_mec", choices=["greedy_mec", "greedy_conf", "greedy_bic", "global_scoring", "PC", "blind"], help='What algorithm to use')
parser.add_argument('--dataset', default="child", type=str, help='What dataset to use')
parser.add_argument('--tabular', default=0, type=int, help='If 1 use tabular expert, else use gpt3')
parser.add_argument('--prior', default="mec", choices=["mec", "independent"])
parser.add_argument('--probability', default="posterior", choices=["posterior", "prior", "likelihood"])
parser.add_argument('--pubmed-sources', type=int, help='How many PubMed sources to retrieve')

parser.add_argument('--epsilon', default=0.05, type=float, help='algorithm error tolerance')
parser.add_argument('--gpt-tmp', default=0.7, type=float, help='gpt temperature for randomness')
parser.add_argument('-tol', '--tolerance', default=0.101, type=float, help='algorithm error tolerance')

parser.add_argument('--seed', type=int, default=20230515, help='random seed')
parser.add_argument('--verbose', default=0, type=int, help='For debugging purposes')
parser.add_argument('--wandb', default=False, action="store_true", help='to log on wandb')

def blindly_follow_expert(observed_arcs, model, cpdag, *args, **kwargs):

    return [list(observed_arcs) + list(cpdag.arcs)], observed_arcs, model(observed_arcs, observed_arcs)

if __name__ == '__main__':

    args = parser.parse_args()

    wandb.login(key='246c8f672f0416b12172d64574c12d8a7ddae387')

    wandb.init(config=args,
               project='causal discovery',
               mode=None if args.wandb else 'disabled'
               )

    random.seed(args.seed)
    np.random.seed(args.seed)

    match args.algo:
        case "greedy_mec":
            algo = greedy_search_mec_size
        case "greedy_conf":
            algo = greedy_search_confidence
        case "greedy_bic":
            algo = greedy_search_bic
            args.tolerance = None

        case "global_scoring":
            from algo.global_scoring import global_scoring
            algo = global_scoring
            args.tolerance = None

        case "PC":
            algo = lambda a, b, mec, c, tol: (mec, dict(), 1.)
            args.tolerance = None
        case "blind":
            algo = blindly_follow_expert
            args.tolerance = None
    
    match args.prior:
        case "mec":
            from models.priors import MECPrior
            prior_type = MECPrior
        
        case "independent":
            from models.priors import IndependentPrior
            prior_type = IndependentPrior
    
    if not os.path.exists("_raw_bayesian_nets"):
        from utils.download_datasets import download_datasets
        download_datasets()

    print(args)

    true_G, _ = generate_dataset('_raw_bayesian_nets/' + args.dataset + '.bif')
    cpdag = DAG.from_nx(true_G).cpdag()

    plot_heatmap(nx.to_numpy_array(true_G), lbls=true_G.nodes(), dataset=args.dataset, name='true_g.pdf')
    undirected_edges = get_undirected_edges(true_G, verbose=args.verbose)

    #lm_error = calibrate(directed_edges, codebook) 
    #print('Calibration Error: ', lm_error)

    if args.tabular:
        oracle = EpsilonOracle(undirected_edges, epsilon=args.epsilon)
        observations = oracle.decide_all()
        likelihoods = oracle.likelihoods

    else:
        try:
            codebook = pd.read_csv('codebooks/' + args.dataset + '.csv')
        except:
            print('cannot load the codebook')
            codebook = None
    
        likelihoods = get_lms_probs(undirected_edges, codebook, tmp=args.gpt_tmp, seed=args.seed)
        observations = likelihoods.keys()

    print("\nTrue Orientations:", undirected_edges)
    print("\nOrientations given by the expert:", observations)
    prior = prior_type(cpdag)
    model = NoisyExpert(prior, likelihoods)

    match args.probability:
        case "posterior":
            prob_method = model.posterior
        
        case "likelihood":
            prob_method = model.likelihood

        case "prior":
            prob_method = lambda _, edges: prior(edges)

    new_mec, decisions, p_correct = algo(observations, prob_method, cpdag, undirected_edges, tol=args.tolerance)

    if args.verbose:
        print("\nFinal MEC", new_mec)

    shd, learned_adj = get_mec_shd(true_G, new_mec)
    
    learned_G = nx.from_numpy_array(learned_adj, create_using=nx.DiGraph)
    learned_G = nx.relabel_nodes(learned_G, {i: n for i, n in zip(learned_G.nodes, true_G.nodes)})

    diff = nx.difference(learned_G, true_G)
    print("\nFinal wrong orientations:", diff.edges)

    #shds_scores = np.array([v for v in shds.values()])
    print('\nConfidence true DAG is in final MEC: %.3f' % p_correct)
    print("Final MEC's SHD: ", shd)
    print('MEC size: ', len(new_mec))
    wandb.log({'mec size': len(new_mec),
               'shd': shd,
               'prob-correct': p_correct,
               'true-still-in-MEC': is_dag_in_mec(true_G, new_mec)})
    wandb.finish()

    plot_heatmap(learned_adj, lbls=true_G.nodes(), dataset=args.dataset, name=f'pred-{args.algo}-prior={args.prior}-tol={args.tolerance}-tabular={args.tabular}.pdf')