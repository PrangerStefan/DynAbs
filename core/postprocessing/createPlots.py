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
import pandas as pd             # Import Pandas to store data in frames
import matplotlib.pyplot as plt # Import Pyplot to generate plots

# Load main classes and methods
from matplotlib import cm
from scipy.spatial import ConvexHull
from matplotlib.patches import Rectangle
import matplotlib.patches as patches

from ..commons import printWarning, mat_to_vec, cm2inch
from core.monte_carlo import monte_carlo

def draw_hull(points, color, linewidth=0.1):

    # Plot hull of the vertices        
    try: 
        hull = ConvexHull(points)
        
        # Get the indices of the hull points.
        hull_indices = hull.vertices
        
        # These are the actual points.
        hull_pts = points[hull_indices, :]
        
        plt.fill(hull_pts[:,0], hull_pts[:,1], fill=False, edgecolor=color, lw=linewidth)
        
        print('Convex hull plotted')
        
    except:
        plt.plot(points[:,0], points[:,1],
                 color=color, lw=linewidth)
        
        print('Line plotted')

def partition_plot(i_show, i_hide, ScAb, cut_value, act=None, stateLabels=False):
    '''

    Returns
    -------
    None.

    '''
    
    is1, is2 = i_show
    
    fig, ax = plt.subplots(figsize=cm2inch(6.1, 5))
    
    plt.xlabel('Var $1$', labelpad=0)
    plt.ylabel('Var $2$', labelpad=0)

    width = ScAb.spec.partition['width']
    number = ScAb.spec.partition['number']
    origin = ScAb.spec.partition['origin']
    
    min_xy = ScAb.spec.partition['boundary'][:,0]
    max_xy = ScAb.spec.partition['boundary'][:,1]
    
    # Compute where to show ticks on the axis
    ticks_x = np.round(np.linspace(min_xy[is1], max_xy[is1], number[is1]+1), 4)
    ticks_y = np.round(np.linspace(min_xy[is2], max_xy[is2], number[is2]+1), 4)
    
    show_every = np.round(number / 5)
    ticks_x_labels = [v if i % show_every[is1] == 0 else '' for i,v in enumerate(ticks_x)]
    ticks_y_labels = [v if i % show_every[is2] == 0 else '' for i,v in enumerate(ticks_y)]
    
    # Set ticks and tick labels
    ax.set_xticks(ticks_x)
    ax.set_yticks(ticks_y)
    ax.set_xticklabels(ticks_x_labels)
    ax.set_yticklabels(ticks_y_labels)
    
    # x-axis
    for i, tic in enumerate(ax.xaxis.get_major_ticks()):
        if ticks_x_labels[i] == '':
            tic.tick1line.set_visible(False)
            tic.tick2line.set_visible(False)
    
    # y-axis
    for i, tic in enumerate(ax.yaxis.get_major_ticks()):
        if ticks_y_labels[i] == '':
            tic.tick1line.set_visible(False)
            tic.tick2line.set_visible(False)
    
    # Show gridding of the state space
    plt.grid(which='major', color='#CCCCCC', linewidth=0.3)
    
    # Goal x-y limits
    min_xy_scaled = 1.5 * (min_xy - origin) + origin
    max_xy_scaled = 1.5 * (max_xy - origin) + origin
    
    ax.set_xlim(min_xy_scaled[is1], max_xy_scaled[is1])
    ax.set_ylim(min_xy_scaled[is2], max_xy_scaled[is2])
    
    ax.set_title("Partition plot", fontsize=10)
    
    # Draw goal states
    for goal in ScAb.partition['goal']:
        
        if all(ScAb.partition['R']['center'][goal, list(i_hide)] == cut_value):
        
            goal_lower = ScAb.partition['R']['low'][goal, [is1, is2]]
            goalState = patches.Rectangle(goal_lower, width=width[is1], 
                                  height=width[is2], color="green", 
                                  alpha=0.3, linewidth=None)
            ax.add_patch(goalState)
    
    # Draw critical states
    for crit in ScAb.partition['critical']:
        
        if all(ScAb.partition['R']['center'][crit, list(i_hide)] == cut_value):
        
            critStateLow = ScAb.partition['R']['low'][crit, [is1, is2]]
            criticalState = patches.Rectangle(critStateLow, width=width[is1], 
                                      height=width[is2], color="red", 
                                      alpha=0.3, linewidth=None)
            ax.add_patch(criticalState)
    
    with plt.rc_context({"font.size": 5}):        
        # Draw every X-th label
        if stateLabels:
            skip = 1
            for i in range(0, ScAb.partition['nr_regions'], skip):
                
                if all(ScAb.partition['R']['center'][i, list(i_hide)] == cut_value):
                                
                    ax.text(ScAb.partition['R']['center'][i,is1], 
                            ScAb.partition['R']['center'][i,is2], i, \
                            verticalalignment='center', 
                            horizontalalignment='center' ) 
    
    if not act is None:
        
        plt.scatter(act.center[is1], act.center[is2], c='red', s=20)
        
        print(' - Print backward reachable set of action', act.idx)
        draw_hull(act.backreach, color='red')
        
        if hasattr(act, 'backreach_infl'):
            draw_hull(act.backreach_infl, color='blue')
        
        for s in act.enabled_in:
            center = ScAb.partition['R']['center'][s]
            plt.scatter(center[is1], center[is2], c='blue', s=8)
    
    # Set tight layout
    fig.tight_layout()
    
    # Save figure
    filename = ScAb.setup.directories['outputF']+'partition_plot'
    for form in ScAb.setup.plotting['exportFormats']:
        plt.savefig(filename+'.'+str(form), format=form, bbox_inches='tight')
        
    plt.show()

def set_axes_equal(ax: plt.Axes):
    """
    Set 3D plot axes to equal scale.

    Make axes of 3D plot have equal scale so that spheres appear as
    spheres and cubes as cubes.  Required since `ax.axis('equal')`
    and `ax.set_aspect('equal')` don't work on 3D.
    """
    
    limits = np.array([
        ax.get_xlim3d(),
        ax.get_ylim3d(),
        ax.get_zlim3d(),
    ])
    origin = np.mean(limits, axis=1)
    radius = 0.5 * np.max(np.abs(limits[:, 1] - limits[:, 0]))
    _set_axes_radius(ax, origin, radius)
    
def _set_axes_radius(ax, origin, radius):
    x, y, z = origin
    ax.set_xlim3d([x - radius, x + radius])
    ax.set_ylim3d([y - radius, y + radius])

def createProbabilityPlots(setup, N, model, spec, results, partition, mc=None):
    '''
    Create the result plots for the partitionaction instance.

    Parameters
    ----------
    setup : dict
        Setup dictionary.
    plot : dict
        Dictionary containing info about plot settings
    N : int
        Finite time horizon.
    model : dict
        Main dictionary of the LTI system model.
    results : dict
        Dictionary containing all results from solving the MDP.
    partition : dict
        Dictionay containing all information of the partitioning
    mc : dict
        Dictionary containing all data relevant to the Monte Carlo simulations.

    Returns
    -------
    None.

    '''
    
    # Plot 2D probability plot over time
    if N/2 != round(N/2):
        printWarning('WARNING: '+str(N/2)+' is no valid integer index')
        printWarning('Print results for time index k='+
                     str(int(np.floor(N/2)-1))+' instead')
    
    if mc != None:
        fig = plt.figure(figsize=cm2inch(14, 7))
    else:
        fig = plt.figure(figsize=cm2inch(8, 6))
    ax = plt.gca()
    
    # Plot probability reachabilities
    color = next(ax._get_lines.prop_cycler)['color']
    
    plt.plot(results['optimal_reward'], label='k=0', linewidth=1, color=color)
    if mc != None and not setup.montecarlo['init_states']:
        plt.plot(mc['reachability'], label='Monte carlo (k=0)', \
                 linewidth=1, color=color, linestyle='dashed')
                
    # Styling plot
    plt.xlabel('States')
    plt.ylabel('Reachability probability')
    plt.legend(loc="upper left")
    
    # Set tight layout
    fig.tight_layout()
                
    # Save figure
    filename = setup.directories['outputFcase']+'reachability_probability'
    for form in setup.plotting['exportFormats']:
        plt.savefig(filename+'.'+str(form), format=form, bbox_inches='tight')
    
    plt.show()
    
    ######################
    # Determine dimension of model
    m = spec.partition['number']
    
    # Plot 3D probability plot for selected time steps
    if model.n > 2:
        printWarning('Nr of dimensions > 2, so 3D reachability plot omitted')
    
    else:
        # Plot 3D probability results
        plot3D      = dict()
        
        # Retreive X and Y values of the centers of the regions
        plot3D['x'] = np.zeros(partition['nr_regions'])
        plot3D['y'] = np.zeros(partition['nr_regions'])
        
        for i in range(partition['nr_regions']):
            plot3D['x'][i], plot3D['y'][i] = partition['R']['center'][i]
        
        plot3D['x'] = np.reshape(plot3D['x'], (m[0],m[1]))
        plot3D['y'] = np.reshape(plot3D['y'], (m[0],m[1]))

        # Create figure
        fig = plt.figure(figsize=cm2inch(8,5.33))
        ax  = plt.axes(projection='3d')

        # Determine matrix of probability values
        Z   = np.reshape(results['optimal_reward'], (m[0],m[1]))
        
        # Plot the surface
        surf = ax.plot_surface(plot3D['x'], plot3D['y'], Z, 
                        cmap=cm.coolwarm, linewidth=0, antialiased=False)
        
        # Customize the z axis
        ax.set_zlim(0,1)
        
        # Add a color bar which maps values to colors.
        fig.colorbar(surf, shrink=0.5, aspect=5)
        
        # Set title and axis format
        ax.title.set_text('Reachability probability at time k = 0')
        x_row = mat_to_vec( plot3D['x'] )
        y_col = mat_to_vec( plot3D['y'] )
        n_ticks = 5
        plt.xticks(np.arange(min(x_row), max(x_row)+1, \
                             (max(x_row) - min(x_row))/n_ticks ))
        plt.yticks(np.arange(min(y_col), max(y_col)+1, \
                             (max(y_col) - min(y_col))/n_ticks ))
        plt.tick_params(pad=-3)
            
        plt.xlabel('x_1', labelpad=-6)
        plt.ylabel('x_2', labelpad=-6)
        
        # Set tight layout
        fig.tight_layout()
        
        # Save figure
        filename = setup.directories['outputFcase']+\
            '3d_reachability_k=0'
        
        for form in setup.plotting['exportFormats']:
            plt.savefig(filename+'.'+str(form), format=form, 
                        bbox_inches='tight')
        
        plt.show()
        
        
    
def reachabilityHeatMap(ScAb, montecarlo = False, title = 'auto'):
    '''
    Create heat map for the reachability probability from any initial state.

    Parameters
    ----------
    ScAb : abstraction instance
        Full object of the abstraction being plotted for

    Returns
    -------
    None.

    '''
    
    import seaborn as sns
    from ..define_partition import definePartitions

    if ScAb.model.n == 2:
        
        x_nr = ScAb.spec.partition['number'][0]
        y_nr = ScAb.spec.partition['number'][1]
        
        cut_centers = definePartitions(ScAb.model.n, [x_nr, y_nr], 
               ScAb.spec.partition['width'], 
               ScAb.spec.partition['origin'], onlyCenter=True)['center']

    if ScAb.model.name == 'building_2room':
    
        x_nr = ScAb.spec.partition['number'][0]
        y_nr = ScAb.spec.partition['number'][1]
        
        cut_centers = definePartitions(ScAb.model.n, [x_nr, y_nr, 1, 1], 
               ScAb.spec.partition['width'], 
               ScAb.spec.partition['origin'], onlyCenter=True)['center']
        
    if ScAb.model.name == 'anaesthesia_delivery':
    
        x_nr = ScAb.spec.partition['number'][0]
        y_nr = ScAb.spec.partition['number'][1]
        
        orig = np.concatenate((ScAb.spec.partition['origin'][0:2],
                              [9.25]))
        
        cut_centers = definePartitions(ScAb.model.n, [x_nr, y_nr, 1], 
               ScAb.spec.partition['width'], 
               orig, onlyCenter=True)['center']
        
        print(cut_centers)
        
    elif ScAb.model.n == 4:
        
        x_nr = ScAb.spec.partition['number'][0]
        y_nr = ScAb.spec.partition['number'][2]
        
        cut_centers = definePartitions(ScAb.model.n, [x_nr, 1, y_nr, 1], 
               ScAb.spec.partition['width'], 
               ScAb.spec.partition['origin'], onlyCenter=True)['center']
                          
    cut_values = np.zeros((x_nr, y_nr))
    cut_coords = np.zeros((x_nr, y_nr, ScAb.model.n))
    
    cut_idxs = [ScAb.partition['R']['c_tuple'][tuple(c)] for c in cut_centers 
                                   if tuple(c) in ScAb.partition['R']['c_tuple']]              
    
    for i,(idx,center) in enumerate(zip(cut_idxs, cut_centers)):
        
        j = i % y_nr
        k = i // y_nr
        
        if montecarlo:
            cut_values[k,j] = ScAb.mc['reachability'][idx] 
        else:
            cut_values[k,j] = ScAb.results['optimal_reward'][idx]
        cut_coords[k,j,:] = center
    
    cut_df = pd.DataFrame( cut_values, index=cut_coords[:,0,0], 
                           columns=cut_coords[0,:,1] )
    
    fig = plt.figure(figsize=cm2inch(9, 8))
    ax = sns.heatmap(cut_df.T, cmap="jet", #YlGnBu
             vmin=0, vmax=1)
    ax.figure.axes[-1].yaxis.label.set_size(20)
    ax.invert_yaxis()
    
    ax.set_xlabel('Var 1', fontsize=15)
    ax.set_ylabel('Var 2', fontsize=15)
    if title == 'auto':
        ax.set_title("N = "+str(ScAb.args.noise_samples), fontsize=20)
    else:
        ax.set_title(str(title), fontsize=20)
    
    # Set tight layout
    fig.tight_layout()

    # Save figure
    filename = ScAb.setup.directories['outputFcase']+'safeset_N=' + \
                str(ScAb.args.noise_samples)
    for form in ScAb.setup.plotting['exportFormats']:
        plt.savefig(filename+'.'+str(form), format=form, bbox_inches='tight')
        
    plt.show()