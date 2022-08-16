#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
 ______________________________________
|                                      |
|  SCENARIO-BASED ABSTRACTION PROGRAM  |
|______________________________________|

Implementation of the method proposed in the paper:

  Thom Badings, Alessandro Abate, David Parker, Nils Jansen, Hasan Poonawala & 
  Marielle Stoelinga (2021). Sampling-based Robust Control of Autonomous 
  Systems with Non-Gaussian Noise. AAAI 2022.

Originally coded by:        Thom S. Badings
Contact e-mail address:     thom.badings@ru.nl>
______________________________________________________________________________
"""

import numpy as np              # Import Numpy for computations
import itertools                # Import to crate iterators
import csv                      # Import to create/load CSV files
import sys                      # Allows to terminate the code at some point
import os                       # Import OS to allow creationg of folders
import random                   # Import to use random variables
import pandas as pd             # Import Pandas to store data in frames
import subprocess

from .define_model import find_connected_components
from .define_partition import definePartitions, define_spec_region
from .compute_probabilities import computeScenarioBounds_error
from .commons import tic, ticDiff, tocDiff, table, printWarning
from .compute_actions import enabledActionsImprecise, epistemic_error
from .create_iMDP import mdp
from .postprocessing.createPlots import partition_plot

from .cvx_opt import LP_vertices_contained

from .action_classes import action, backreachset

'''
------------------------------------------------------------------------------
Main filter-based abstraction object definition
------------------------------------------------------------------------------
'''

class Abstraction(object):
    '''
    Main abstraction object    
    '''
    
    def __init__(self):
        '''
        Initialize the scenario-based abstraction object.

        Returns
        -------
        None.

        '''
        
        print('Model loaded:')
        print(' -- Dimension of the state:',self.model.n)
        print(' -- Dimension of the control input:',self.model.p)
        
        # Number of simulation time steps
        self.N = int(self.spec.end_time / self.model.lump)
        
        # Determine if model has parametric uncertainty
        if hasattr(self.model, 'A_set'):
            print(' --- Model has parametric uncertainty, so set flag')
            self.flags['parametric'] = True
        else:
            print(' --- Model does not have parametric uncertainty')
            self.flags['parametric'] = False
        
        # Determine if model is underactuated
        if self.model.p < self.model.n:
            print(' --- Model is not fully actuated, so set flag')
            self.flags['underactuated'] = True
        else:
            print(' --- Model is fully actuated')
            self.flags['underactuated'] = False
        
        self.time['0_init'] = tocDiff(False)
        print('Abstraction object initialized - time:',self.time['0_init'])
    
    
    
    def _defAllCorners(self):
        '''
        Returns the vertices of every region in the partition (as nested list)

        Returns
        -------
        list
            Nested list of all vertices of all regions.

        '''
            
        # Create all combinations of n bits, to reflect combinations of all 
        # lower/upper bounds of partitions
        bitCombinations = list(itertools.product([0, 1], 
                               repeat=self.model.n))
        bitRelation     = ['low','upp']
        
        # Calculate all corner points of every partition. Every partition has 
        # an upper and lower bounnd in every state (dimension). Hence, the 
        # every partition has 2^n corners, with n the number of states.
        allOriginPointsNested = [[[
            self.partition['R'][bitRelation[bit]][i][bitIndex] 
                for bitIndex,bit in enumerate(bitList)
            ] for bitList in bitCombinations 
            ] for i in range(self.partition['nr_regions'])
            ]
        
        return np.array(allOriginPointsNested)
       
    
    
    def define_states(self):
        ''' 
        Define the discrete state space partition and target points
        
        Returns
        -------
        None.
        '''
        
        # Create partition
        print('\nComputing partition of the state space...')
        
        # Define partitioning of state-space
        self.partition = dict()
        
        # Determine origin of partition
        self.spec.partition['number'] = np.array(self.spec.partition['number'])
        self.spec.partition['width'] = np.array([-1,1]) @ self.spec.partition['boundary'].T / self.spec.partition['number']
        self.spec.partition['origin'] = 0.5 * np.ones(2) @ self.spec.partition['boundary'].T
        
        self.partition['R'] = definePartitions(self.model.n,
                            self.spec.partition['number'],
                            self.spec.partition['width'],
                            self.spec.partition['origin'],
                            onlyCenter = False)
        
        self.partition['nr_regions'] = len(self.partition['R']['center'])
        
        # Determine goal regions
        self.partition['goal'], self.partition['goal_slices'], self.partition['goal_idx'] = define_spec_region(
            allCenters = self.partition['R']['c_tuple'], 
            sets = self.spec.goal,
            partition = self.spec.partition,
            borderOutside = True)
        
        # Determine critical regions
        self.partition['critical'], self.partition['critical_slices'], self.partition['critical_idx'] = define_spec_region(
            allCenters = self.partition['R']['c_tuple'], 
            sets = self.spec.critical,
            partition = self.spec.partition,
            borderOutside = True)
        
        print(' -- Number of regions:',self.partition['nr_regions'])
        print(' -- Number of goal regions:',len(self.partition['goal']))
        print(' -- Number of critical regions:',len(self.partition['critical']))

        self.time['1_partition'] = tocDiff(False)
        print('Discretized states defined - time:',self.time['1_partition'])
        
        self.partition['allCorners']     = self._defAllCorners()
        self.partition['allCornersFlat'] = np.concatenate(self.partition['allCorners'])



    def define_target_points(self):
        
        self.actions = {'obj': {},
                        'backreach_obj': {},
                        'tup2idx': {},
                        'extra_act': []}
        
        if self.flags['underactuated']:
            
            print('\nDefining backward reachable sets...')
            
            for name, error in self.spec.error['max_control_error'].items():
                # Compute the backward reachable set objects
                self.actions['backreach_obj'][name] = backreachset(name, error)
                
                # Compute the zero-shifted inflated backward reachable set
                self.actions['backreach_obj'][name].compute_default_set(self.model)
                
            backreach_obj = self.actions['backreach_obj']['default']
        else:
            backreach_obj = None
                
        print('\nDefining target points...')
        
        # Create the target point for every action (= every state)
        if type(self.spec.targets['number']) == str:
            # Set default target points to the center of every region
            
            # self.spec.targets['number'] = self.spec.partition['number']
            # self.spec.targets['width'] = self.spec.partition['width']
            # self.spec.targets['origin'] = self.spec.partition['origin']
            
            for center, (tup,idx) in zip(self.partition['R']['center'],
                                        self.partition['R']['idx'].items()):
                
                self.actions['obj'][idx] = action(idx, self.model, center, tup, 
                                                  backreach_obj)
                self.actions['tup2idx'][tup] = idx
            
        else:
            # self.spec.targets['number'] = np.array(self.spec.targets['number'])
            # self.spec.targets['width'] = np.array([-1,1]) @ self.spec.targets['boundary'].T / self.spec.targets['number']
            # self.spec.targets['origin'] = 0.5 * np.ones(2) @ self.spec.targets['boundary'].T
            
            print(' -- Compute manual target points; no. per dim:',self.spec.targets['number'])
        
            ranges = map(np.linspace, self.spec.targets['boundary'][:,0],
                         self.spec.targets['boundary'][:,1], self.spec.targets['number'])
            
            tuples = map(np.arange, np.zeros(self.model.n),
                         self.spec.targets['number'])
            
            for idx,(center,tup) in enumerate(zip(itertools.product(*ranges),
                                                itertools.product(*tuples))):
                
                self.actions['obj'][idx] = action(idx, self.model, 
                                                  np.array(center), tup, 
                                                  backreach_obj)
                self.actions['tup2idx'][tup] = idx
        
        nr_default_act = len(self.actions['obj'])
        
        # Add additional target points if this is requested
        if 'extra' in self.spec.targets:
            
            if self.flags['underactuated']:
                backreach_obj = self.actions['backreach_obj']['extra']
            else:
                backreach_obj = None
            
            for i,center in enumerate(self.spec.targets['extra']):    
                
                self.actions['obj'][nr_default_act+i] = action(nr_default_act+i, self.model, center, -i, backreach_obj)
                self.actions['extra_act'] += [self.actions['obj'][nr_default_act+i]]
        
        self.actions['nr_actions'] = len(self.actions['obj'])



    def define_actions(self):
        ''' 
        Determine which actions are actually enabled.
        
        Returns
        -------
        None.
        '''
            
        print('\nComputing set of enabled actions...')
        
        # Find the connected components of the system
        dim_n, dim_p = find_connected_components(self.model.A, self.model.B,
                                                 self.model.n, self.model.p)
        
        print(' -- Number of actions (target points):', self.actions['nr_actions'])

        enabled = [None for i in range(len(dim_n))]
        enabled_inv = [None for i in range(len(dim_n))]
        error = [None for i in range(len(dim_n))]

        for i,(dn,dp) in enumerate(zip(dim_n, dim_p)):
        
            print(' --- In dimensions of state', dn,'and control', dp)    
        
            enabled[i], enabled_inv[i], error[i] = enabledActionsImprecise(
                self.setup, self.flags, self.partition, self.actions, 
                self.model, self.spec, dn, dp)
        
        self.TEMP_dim_n = dim_n
        self.TEMP_enabled = enabled
        self.TEMP_enabled_inv = enabled_inv
        self.TEMP_error = error
        
        nr_act = self._composeEnabledActions(dim_n, enabled, 
                                             enabled_inv, error)
    
        # Add extra actions
        BRS_0 = self.actions['backreach_obj']['default'].verts_infl
        LP = LP_vertices_contained(self.model, BRS_0.shape, 
                                   solver=self.setup.cvx['solver'])
        
        if self.flags['parametric']:
            epist = epistemic_error(self.model)
        else:
            epist = None
        
        for act in self.actions['extra_act']:
                
            # Set current backward reachable set as parameter
            LP.set_backreach(act.backreach_infl)
            
            s_min_list = []
            
            # Try each potential predecessor state
            for s_min in range(self.partition['nr_regions']):
                
                # Skip if this is a critical state
                if s_min in self.partition['critical']:
                    continue
                
                unique_verts = np.unique(self.partition['allCorners'][s_min], axis=0)
                
                # If the problem is feasible, then action is enabled in this state
                if LP.solve(unique_verts):
                    
                    # Add state to the list of enabled states
                    s_min_list += [s_min]
                    
                    # Enable the current action in the current state
                    self.actions['enabled'][s_min].add(act.idx)
                       
                    act.enabled_in.add(s_min)
                    
            # Retrieve control error negative/positive
            control_error = act.backreach_obj.max_control_error
                    
            # If a parametric model is used
            if not epist is None and len(s_min_list) > 0:
                
                # Retrieve list of unique vertices of predecessor states
                s_vertices = self.partition['allCorners'][s_min_list]
                s_vertices_unique = np.unique(np.vstack(s_vertices), axis=0)
            
                # Compute the epistemic error
                epist_error_neg, epist_error_pos = epist.compute(s_vertices_unique)
                
                # Store the control error for this action
                act.error = {'neg': control_error[:,0] + epist_error_neg,
                             'pos': control_error[:,1] + epist_error_pos}
                
            else:
                
                # Store the control error for this action
                act.error = {'neg': control_error[:,0],
                             'pos': control_error[:,1]}
            
        ### PLOT ###
        if self.args.partition_plot:
            
            if 'partition_plot_action' in self.model.setup:
                a = self.model.setup['partition_plot_action']
            else:
                a = np.round(self.actions['nr_actions'] / 2).astype(int)
                
            partition_plot((0,1), (), self, cut_value=np.array([]), act=self.actions['obj'][a] )
            for a in range(0,self.actions['nr_actions'],100):
                print('Create plot of partition with backward reachable set...')
                
                partition_plot((0,1), (), self, cut_value=np.array([]), act=self.actions['obj'][a] )
                
        print(nr_act,'actions enabled')
        if nr_act == 0:
            printWarning('No actions enabled at all, so terminate')
            sys.exit()
    
        self.time['2_enabledActions'] = tocDiff(False)
        print('Enabled actions define - time:',self.time['2_enabledActions'])
        
        
        
    def _composeEnabledActions(self, dim_n, enabled_sub, enabled_sub_inv, 
                               control_error_sub):
        
        # Initialize variables
        self.actions['enabled'] = [set() for i in range(self.partition['nr_regions'])]
            
        ## Merge together successor states (per action)
        enabled_inv_keys = itertools.product(*[enabled_sub_inv[i].keys() 
                                               for i in range(len(dim_n))])
        enabled_inv_vals = itertools.product(*[enabled_sub_inv[i].values() 
                                                for i in range(len(dim_n))])
        
        # Precompute matrix to put together control error
        mats = [None] * len(dim_n)
        for h,dim in enumerate(dim_n):
            mats[h] = np.zeros((self.model.n, len(dim)))
            for j,i in enumerate(dim):
                mats[h][i,j] = 1
        
        nr_act = 0
        
        # Zipping over the product of the keys/values of the dictionaries
        for keys, vals_enab in zip(enabled_inv_keys, enabled_inv_vals):
        # for keys, vals_enab in zip(enabled_inv_keys, enabled_inv_vals):
            
            vals_error = [control_error_sub[i][key] for i,key in enumerate(keys)]
            
            # Add tuples to get the compositional state
            act_idx = self.actions['tup2idx'][tuple(np.sum(keys, axis=0))]
            act_obj = self.actions['obj'][act_idx]
            
            s_elems = list(itertools.product(*vals_enab))
            s_enabledin  = np.sum(s_elems, axis=1)
            
            for s in s_enabledin:
                
                state = self.partition['R']['idx'][tuple(s)]
                
                # Skip if v is a critical state
                if state in self.partition['critical']:
                    continue
                
                act_obj.enabled_in.add( state )
                self.actions['enabled'][state].add( act_idx )
            
            # Check if action is enabled in any state
            if len(act_obj.enabled_in) > 0:
                nr_act += 1
            
            # Compute control error for this action
            if hasattr(self.model, 'Q_uncertain'):
                # Also account for the uncertain disturbances
                act_obj.error = {
                    'pos': np.sum([mats[z] @ vals_error[z]['pos'] for z in 
                                   range(len(dim_n))], axis=0) + self.model.Q_uncertain['max'],
                    'neg': np.sum([mats[z] @ vals_error[z]['neg'] for z in 
                                   range(len(dim_n))], axis=0) + self.model.Q_uncertain['min']
                    }
            
            else:
                # No uncertain disturbance to account for
                act_obj.error = {
                    'pos': np.sum([mats[z] @ vals_error[z]['pos'] for z in 
                                   range(len(dim_n))], axis=0),
                    'neg': np.sum([mats[z] @ vals_error[z]['neg'] for z in 
                                   range(len(dim_n))], axis=0)
                    }
            
        return nr_act
        
        
        
    def build_iMDP(self):
        '''
        Build the (i)MDP and create all respective PRISM files.

        Returns
        -------
        model_size : dict
            Dictionary describing the number of states, choices, and 
            transitions.

        '''
        
        problem_type = self.spec.problem_type
        
        # Initialize MDP object
        self.mdp = mdp(self.setup, self.N, self.partition, self.actions)
        
        # Create PRISM file (explicit way)
        model_size, self.mdp.prism_file, self.mdp.spec_file, \
        self.mdp.specification = \
            self.mdp.writePRISM_explicit(self.actions, self.partition, self.trans, problem_type, 
                                         self.args.mdp_mode)   

        self.time['4_MDPcreated'] = tocDiff(False)
        print('MDP created - time:',self.time['4_MDPcreated'])
        
        return model_size


            
    def solve_iMDP(self):
        '''
        Solve the (i)MDP usign PRISM

        Returns
        -------
        None.

        '''

        prism_folder = self.setup.mdp['prism_folder'] 
        
        print('\n+++++++++++++++++++++++++++++++++++++++++++++++++++++\n')
        
        print('Starting PRISM...')
        
        spec = self.mdp.specification
        mode = self.args.mdp_mode
        
        print(' -- Running PRISM with specification for mode',
              mode.upper()+'...')
    
        file_prefix = self.setup.directories['outputFcase'] + "PRISM_" + mode
        policy_file = file_prefix + '_policy.csv'
        vector_file = file_prefix + '_vector.csv'
    
        options = ' -ex -exportadv "'+policy_file+'"'+ \
                  ' -exportvector "'+vector_file+'"'
    
        print(' --- Execute PRISM command for EXPLICIT model description')        

        model_file      = '"'+self.mdp.prism_file+'"'             
    
        # Explicit model
        command = prism_folder+"bin/prism -javamaxmem "+ \
            str(self.args.prism_java_memory)+"g -importmodel "+model_file+" -pf '"+ \
            spec+"' "+options
        
        subprocess.Popen(command, shell=True).wait()    
        
        # Load PRISM results back into Python
        self.loadPRISMresults(policy_file, vector_file)
            
        self.time['5_MDPsolved'] = tocDiff(False)
        print('MDP solved in',self.time['5_MDPsolved'])
        
        
    
    def loadPRISMresults(self, policy_file, vector_file):
        '''
        Load results from existing PRISM output files.

        Parameters
        ----------
        policy_file : str
            Name of the file to load the optimal policy from.
        vector_file : str
            Name of the file to load the optimal policy from.

        Returns
        -------
        None.

        '''
        
        self.results = dict()
        
        # Read policy CSV file
        policy_all = pd.read_csv(policy_file, header=None).iloc[:, 3:].\
            fillna(-1).to_numpy()
            
        # Flip policy upside down (PRISM generates last time step at top!)
        policy_all = np.flipud(policy_all)
        
        self.results['optimal_policy'] = np.zeros(np.shape(policy_all), dtype=int)
        
        rewards_k0 = pd.read_csv(vector_file, header=None).iloc[3:].to_numpy()
        self.results['optimal_reward'] = rewards_k0.flatten()
        
        # Convert avoid probability to the safety probability
        if self.spec.problem_type:
            self.results['optimal_reward'] = 1 - self.results['optimal_reward']
        
        for i,row in enumerate(policy_all):    
            for j,value in enumerate(row):
                
                # If value is not -1 (means no action defined)
                if value != -1:
                    # Split string
                    value_split = value.split('_')
                    # Store action ID
                    self.results['optimal_policy'][i,j] = int(value_split[1])
                else:
                    # If no policy is known, set to -1
                    self.results['optimal_policy'][i,j] = int(value)
        
        
        
    def generate_probability_plots(self):
        '''
        Generate (optimal reachability probability) plots
        '''
        
        print('\nGenerate plots')
        
        if self.partition['nr_regions'] <= 5000:
        
            from .postprocessing.createPlots import createProbabilityPlots
        
            if not hasattr(self, 'mc'):
                self.mc = None    
        
            createProbabilityPlots(self.setup, self.N, self.model, self.spec,
                                   self.results, self.partition, self.mc)
                
        else:
            printWarning("Omit probability plots (nr. of regions too large)")
            
            
            
    def generate_heatmap(self):
            
            from core.postprocessing.createPlots import reachabilityHeatMap
            
            # Create heat map
            reachabilityHeatMap(self)
     
            
        
###############################



class scenarioBasedAbstraction(Abstraction):
    def __init__(self, args, setup, model_spec):
        '''
        Initialize scenario-based abstraction (ScAb) object

        Parameters
        ----------
        setup : dict
            Setup dictionary.
        model : dict
            Base model for which to create the abstraction.

        Returns
        -------
        None.

        '''
        
        # Copy setup to internal variable
        self.setup = setup
        self.args  = args
        self.model = model_spec['model']
        self.spec  = model_spec['spec']
        
        # Start timer
        tic()
        ticDiff()
        self.time = dict()
        self.flags = {}
        
        Abstraction.__init__(self)
        
        
        
    def _loadScenarioTable(self, tableFile, k):
        '''
        Load tabulated bounds on the transition probabilities (computed using
        the scenario approach).

        Parameters
        ----------
        tableFile : str
            File from which to load the table.

        Returns
        -------
        memory : dict
            Dictionary containing all loaded probability bounds / intervals.

        '''
        
        if not os.path.isfile(tableFile):
            sys.exit('ERROR: the following table file does not exist:'+
                     str(tableFile))
        
        with open(tableFile, newline='') as csvfile:
            reader = csv.reader(csvfile, delimiter=' ', quotechar='|')
            
            # Skip header row
            next(reader)
            
            memory = np.full((k+1, 2), fill_value = -1, dtype=float)
                
            for i,row in enumerate(reader):
                
                strSplit = row[0].split(',')
                
                value = [float(i) for i in strSplit[-2:]]
                memory[int(strSplit[0])] = value
                    
        return memory
        
    
    
    def _computeProbabilityBounds(self, tab, k):
        '''
        Compute transition probability intervals (bounds)

        Parameters
        ----------
        tab : dict
            Table dictionary.
        k : int
            Discrete time step.

        Returns
        -------
        prob : dict
            Dictionary containing the computed transition probabilities.

        '''
        
        prob = dict()
        printEvery = min(100, max(1, int(self.actions['nr_actions']/10)))

        # Compute Gaussian noise samples
        samples = np.random.multivariate_normal(
                        np.zeros(self.model.n), self.model.noise['w_cov'], 
                        size=self.args.noise_samples)
        
        # Cluster samples
        if self.args.sample_clustering > 0:
            
            max_radius = float(self.args.sample_clustering)
            
            remaining_samples       = samples
            remaining_samples_i     = np.arange(len(samples))
            
            clusters0 = {
                'value': [],
                'lb': [],
                'ub': []
                }
            
            while len(remaining_samples) > 0:
                
                # Compute distance between first samples and all others
                distances = np.linalg.norm( remaining_samples[0] - 
                                            remaining_samples, 
                                            axis=1 )
                
                # Add the samples closer than `max_radius` to the first
                # sample to a new cluster
                distances_below = distances < max_radius
                
                cluster_samples = remaining_samples[ distances_below ]
                
                clusters0['value'] += [int(len(remaining_samples_i[ distances_below ]))]
                clusters0['lb'] += [np.min(cluster_samples, axis=0)]
                clusters0['ub'] += [np.max(cluster_samples, axis=0)]
                
                remaining_samples = remaining_samples[ ~distances_below ]
                remaining_samples_i = remaining_samples_i[ ~distances_below ]
                
            clusters0['value']       = np.array(clusters0['value'])
            clusters0['lb']          = np.array(clusters0['lb'])
            clusters0['ub']          = np.array(clusters0['ub'])
            
            print('--',len(samples),'samples clustered into',
                  len(clusters0['value']),'clusters')
            
            assert sum(clusters0['value']) == self.args.noise_samples
            
        else:
            
            clusters0 = {
                'value': np.ones(len(samples)),
                'lb': samples,
                'ub': samples
                }
        
        # For every action (i.e. target point)
        for a_idx, act in self.actions['obj'].items():
            
            # Shift samples by the center of the target set of this action
            clusters = {
                'value': clusters0['value'],
                'lb':    clusters0['lb'] + act.center,
                'ub':    clusters0['ub'] + act.center
                }
            
            # Check if action a is available in any state at all
            if len(act.enabled_in) > 0:
                    
                prob[a_idx] = dict()
                    
                # Checking which samples cannot be contained in a region
                # at the same time is of quadratic complexity in the number
                # of samples. Thus, we disable this above a certain limit.
                if True:
                    exclude = []
                else:
                    exclude = exclude_samples(samples, 
                                      self.spec.partition['width'])
                
                '''
                # Plot one transition plus samples
                a_plot = [np.round(self.actions['nr_actions'] / 2 ).astype(int),
                          self.actions['nr_actions']-1]
                
                st = self.partition['R']['c_tuple'][2.5, -7.5]
                if a_idx in self.actions['enabled'][st]: #[390]: # a_plot:
                    
                    transition_plot(samples, act.error, 
                        (0,1), (), self.args, self.setup, self.model, 
                        self.spec, self.partition,
                        np.array([]), backreach=act.backreach,
                        backreach_inflated=act.backreach_infl)
                '''
                
                prob[a_idx] = computeScenarioBounds_error(self.args, 
                      self.spec.partition, self.partition, self.trans, 
                      clusters, act.error, exclude, verbose=False)
                
                # Print normal row in table
                if a_idx % printEvery == 0:
                    nr_transitions = len(prob[a_idx]['successor_idxs'])
                    tab.print_row([k, a_idx, 
                       'Probabilities computed (transitions: '+
                       str(nr_transitions)+')'])
                
        return prob
    
    
    
    def define_probabilities(self):
        '''
        Define the transition probabilities of the finite-state abstraction 
        (perform for every iteration of the iterative scheme).

        Returns
        -------
        None.

        '''
           
        # Column widths for tabular prints
        col_width = [8,8,8,46]
        tab = table(col_width)
        
        self.trans = {'prob': {}}
                
        print(' -- Loading scenario approach table...')
        
        tableFile = self.setup.directories['base'] + '/input/SaD_probabilityTable_N='+ \
                        str(self.args.noise_samples)+'_beta='+ \
                        str(self.args.confidence)+'.csv'
        
        # Load scenario approach table
        self.trans['memory'] = self._loadScenarioTable(tableFile = tableFile,
                                       k = self.args.noise_samples)
        
        # Retreive type of horizon
        k_range = [0]
        
        print('Computing transition probabilities...')
        
        self.trans['prob'] = dict()
        
        # For every time step in the horizon
        for k in k_range:
            
            # Print header row
            tab.print_row(['K','ACTION','STATUS'], head=True)    
            
            self.trans['prob'][k] = \
                self._computeProbabilityBounds(tab, k)
            
        # Delete iterable variables
        del k
        
        self.time['3_probabilities'] = tocDiff(False)
        print('Transition probabilities calculated - time:',
              self.time['3_probabilities'])
        
        
        
def exclude_samples(samples, width):
    
    N,n = samples.shape
    
    S = np.reshape(samples, (N,n,1))
    diff = S - S.T
    width_tile = np.tile(width, (N,1)).T
    boolean = np.any(diff > width_tile, axis=1) | np.any(diff < -width_tile, axis=1)
    
    mp = map(np.nonzero, boolean)
    exclude = [set(m[0]) for m in mp]
    
    return exclude