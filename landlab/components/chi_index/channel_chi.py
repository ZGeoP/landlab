# -*- coding: utf-8 -*-
"""
Created March 2016.

@author: dejh
"""
from __future__ import print_function
from six.moves import range  # this is Python 3's generator, not P2's list

from landlab import ModelParameterDictionary, Component, FieldError, \
                    FIXED_VALUE_BOUNDARY, BAD_INDEX_VALUE, CLOSED_BOUNDARY
import numpy as np
from itertools import izip


class ChiFinder(Component):
    """
    This component calculates chi indices, sensu Perron & Royden, 2013,
    for a Landlab landscape.

    Construction::

        ChiFinder(grid, reference_concavity=0.5, min_drainage_area=1.e6,
                  reference_area=None, use_true_dx=False)

    Parameters
    ----------
    grid : RasterModelGrid
        A landlab RasterModelGrid.
    reference_concavity : float
        The reference concavity to use in the calculation.
    min_drainage_area : float (m**2)
        The drainage area down to which to calculate chi.
    reference_area : float or None (m**2)
        If None, will default to the mean core cell area on the grid.
        Else, provide a value to use. Essentially becomes a prefactor on the
        value of chi.
    use_true_dx : bool (default False)
        If True, integration to give chi is performed using each value of node
        spacing along the channel (which can lead to a quantization effect,
        and is not preferred by Taylor & Royden). If False, the mean value of
        node spacing along the all channels is assumed everywhere.

    Examples
    --------
    >>> import numpy as np
    >>> from landlab import RasterModelGrid, CLOSED_BOUNDARY
    >>> from landlab.components import FlowRouter, FastscapeEroder
    >>> mg = RasterModelGrid((3, 4), 1.)
    >>> for nodes in (mg.nodes_at_right_edge, mg.nodes_at_bottom_edge,
    ...               mg.nodes_at_top_edge):
    ...     mg.status_at_node[nodes] = CLOSED_BOUNDARY
    >>> _ = mg.add_field('node', 'topographic__elevation', mg.node_x)
    >>> fr = FlowRouter(mg)
    >>> cf = ChiFinder(mg, min_drainage_area=1., reference_concavity=1.)
    >>> _ = fr.route_flow()
    >>> cf.calculate_chi()
    >>> mg.at_node['channel__chi_index'].reshape((3, 4))[1, :]
    array([ 0.5,  1. ,  2. ,  0. ])

    >>> mg2 = RasterModelGrid((5, 5), 100.)
    >>> for nodes in (mg2.nodes_at_right_edge, mg2.nodes_at_bottom_edge,
    ...               mg2.nodes_at_top_edge):
    ...     mg2.status_at_node[nodes] = CLOSED_BOUNDARY
    >>> _ = mg2.add_zeros('node', 'topographic__elevation')
    >>> mg2.at_node['topographic__elevation'][mg2.core_nodes] = mg2.node_x[
    ...     mg2.core_nodes]/1000.
    >>> np.random.seed(0)
    >>> mg2.at_node['topographic__elevation'][
    ...     mg2.core_nodes] += np.random.rand(mg2.number_of_core_nodes)
    >>> fr2 = FlowRouter(mg2)
    >>> sp2 = FastscapeEroder(mg2, K_sp=0.01)
    >>> cf2 = ChiFinder(mg2, min_drainage_area=0., reference_concavity=0.5)
    >>> for i in range(10):
    ...     mg2.at_node['topographic__elevation'][mg2.core_nodes] += 10.
    ...     _ = fr2.route_flow()
    ...     sp2.run_one_timestep(1000.)
    >>> _ = fr2.route_flow()
    >>> cf2.calculate_chi()
    >>> mg2.at_node['channel__chi_index'].reshape(
    ...     (5, 5))  # doctest: +NORMALIZE_WHITESPACE
    array([[   0.        ,    0.        ,    0.        ,    0.        ,  0. ],
           [  77.21941631,  154.43883263,  263.64357846,  261.41943682,  0. ],
           [ 109.20474583,  218.40949166,  152.21469099,  261.41943682,  0. ],
           [  44.5826508 ,   89.16530159,  166.38471791,  275.58946374,  0. ],
           [   0.        ,    0.        ,    0.        ,    0.        ,  0. ]])

    >>> cf2.calculate_chi(min_drainage_area=20000., use_true_dx=True,
    ...                   reference_area=mg2.at_node['drainage_area'].max())
    >>> cf2.chi_indices.reshape((5, 5))  # doctest: +NORMALIZE_WHITESPACE
    array([[   0. ,   0.        ,   0.        ,   0. ,   0. ],
           [   0. , 173.20508076,   0.        ,   0. ,   0. ],
           [   0. ,   0.        , 270.71067812,   0. ,   0. ],
           [   0. , 100.        , 236.60254038,   0. ,   0. ],
           [   0. ,   0.        ,   0.        ,   0. ,   0. ]])
    >>> cf2.hillslope_mask.reshape((5, 5))
    array([[ True,  True,  True,  True,  True],
           [False, False,  True,  True,  True],
           [ True,  True, False,  True,  True],
           [False, False, False,  True,  True],
           [ True,  True,  True,  True,  True]], dtype=bool)

    """
    _name = 'ChiFinder'

    _input_var_names = (
        'topographic__elevation',
        'drainage_area',
        'topographic__steepest_slope',
        'flow_receiver',
        'upstream_node_order',
        'links_to_flow_receiver',
    )

    _output_var_names = (
        'channel__chi_index',
    )

    _var_units = {'topographic__elevation': 'm',
                  'drainage_area': 'm**2',
                  'topographic__steepest_slope': '-',
                  'flow_receiver': '-',
                  'upstream_node_order': '-',
                  'links_to_flow_receiver': '-',
                  'channel__chi_index': 'variable',
                  }

    _var_mapping = {'topographic__elevation': 'node',
                    'drainage_area': 'node',
                    'topographic__steepest_slope': 'node',
                    'flow_receiver': 'node',
                    'upstream_node_order': 'node',
                    'links_to_flow_receiver': 'node',
                    'channel__chi_index': 'node',
                    }

    _var_doc = {'topographic__elevation': 'Surface topographic elevation',
                'drainage_area': 'upstream drainage area',
                'topographic__steepest_slope': ('the steepest downslope ' +
                                                'rise/run leaving the node'),
                'flow_receiver': ('the downstream node at the end of the ' +
                                  'steepest link'),
                'upstream_node_order': ('node order such that nodes must ' +
                                        'appear in the list after all nodes ' +
                                        'downstream of them'),
                'links_to_flow_receiver':
                    ('ID of link downstream of each node, which carries the ' +
                     'discharge'),
                'channel__chi_index': 'the local steepness index',
                }

    def __init__(self, grid, reference_concavity=0.5, min_drainage_area=1.e6,
                 reference_area=None, use_true_dx=False, **kwds):
        """
        Constructor for the component.
        """
        self._grid = grid
        self._reftheta = reference_concavity
        self.min_drainage = min_drainage_area
        if reference_area is None:
            try:
                self._A0 = float(self.grid.cell_area_at_node)
            except TypeError:  # was an array
                self._A0 = self.grid.cell_area_at_node[
                    self.grid.core_nodes].mean()
        else:
            assert reference_area > 0.
            self._A0 = reference_area
        self.use_true_dx = use_true_dx
        self.chi = self._grid.add_zeros('node', 'channel__chi_index')
        self._mask = self.grid.ones('node', dtype=bool)
        # this one needs modifying if smooth_elev
        self._elev = self.grid.at_node['topographic__elevation']

    def calculate_chi(self, **kwds):
        """
        This is the main method. Call it to calculate local chi indices
        at all points with drainage areas greater than *min_drainage_area*.

        This "run" method can optionally take the same parameter set as
        provided at instantiation. If they are provided, they will override
        the existing values from instantiation.

        Chi of any node without a defined value is reported as 0. These nodes
        are also identified in the mask retrieved with :func:`hillslope_mask`.
        """
        self._mask.fill(True)
        self.chi.fill(0.)
        # test for new kwds:
        reftheta = kwds.get('reference_concavity', self._reftheta)
        min_drainage = kwds.get('min_drainage_area', self.min_drainage)
        A0 = kwds.get('reference_area', self._A0)
        if A0 is None:
            try:
                A0 = float(self.grid.cell_area_at_node)
            except TypeError:
                A0 = self.grid.cell_area_at_node[self.grid.core_nodes].mean()
        assert A0 > 0.
        use_true_dx = kwds.get('use_true_dx', self.use_true_dx)

        upstr_order = self.grid.at_node['upstream_node_order']
        # get an array of only nodes with A above threshold:
        valid_upstr_order = upstr_order[self.grid.at_node['drainage_area'][
            upstr_order] >= min_drainage]
        valid_upstr_areas = self.grid.at_node['drainage_area'][
            valid_upstr_order]
        if not use_true_dx:
            chi_integrand = (A0/valid_upstr_areas)**reftheta
            mean_dx = self.mean_channel_node_spacing(valid_upstr_order)
            self.integrate_chi_avg_dx(valid_upstr_order, chi_integrand,
                                      self.chi, mean_dx)
        else:
            chi_integrand = self.grid.zeros('node')
            chi_integrand[valid_upstr_order] = (A0/valid_upstr_areas)**reftheta
            self.integrate_chi_each_dx(valid_upstr_order, chi_integrand,
                                       self.chi)
        # stamp over the closed nodes, as it's possible they can receive infs
        # if min_drainage_area < grid.cell_area_at_node
        self.chi[self.grid.status_at_node == CLOSED_BOUNDARY] = 0.
        self._mask[valid_upstr_order] = False

    def integrate_chi_avg_dx(self, valid_upstr_order, chi_integrand,
                             chi_array, mean_dx):
        """
        Calculates chi at each channel node by summing chi_integrand.

        This method assumes a uniform, mean spacing between nodes. Method is
        deliberately split out for potential cythonization at a later stage.

        Parameters
        ----------
        valid_upstr_order : array of ints
            nodes in the channel network in upstream order.
        chi_integrand : array of floats
            The value (A0/A)**concavity, in upstream order.
        chi_array : array of floats
            Array in which to store chi.
        mean_dx : float
            The mean node spacing in the network.

        Examples
        --------
        >>> import numpy as np
        >>> from landlab import RasterModelGrid, CLOSED_BOUNDARY
        >>> from landlab.components import FlowRouter
        >>> mg = RasterModelGrid((5,4), 1.)
        >>> for nodes in (mg.nodes_at_right_edge, mg.nodes_at_bottom_edge,
        ...               mg.nodes_at_top_edge):
        ...     mg.status_at_node[nodes] = CLOSED_BOUNDARY
        >>> z = mg.node_x.copy()
        >>> z[[5, 13]] = z[6]  # guard nodes
        >>> _ = mg.add_field('node', 'topographic__elevation', z)
        >>> fr = FlowRouter(mg)
        >>> cf = ChiFinder(mg)
        >>> _ = fr.route_flow()
        >>> ch_nodes = np.array([4, 8, 12, 5, 9, 13, 6, 10, 14])
        >>> ch_integrand = 3.*np.ones(9, dtype=float)  # to make calc clearer
        >>> chi_array = np.zeros(mg.number_of_nodes, dtype=float)
        >>> cf.integrate_chi_avg_dx(ch_nodes, ch_integrand, chi_array, 0.5)
        >>> chi_array.reshape((5,4))
        array([[ 0. ,  0. ,  0. ,  0. ],
               [ 1.5,  3. ,  4.5,  0. ],
               [ 1.5,  3. ,  4.5,  0. ],
               [ 1.5,  3. ,  4.5,  0. ],
               [ 0. ,  0. ,  0. ,  0. ]])
        """
        receivers = self.grid.at_node['flow_receiver']
        # because chi_array is all zeros, BC cases where node is receiver
        # resolve themselves
        for (node, integrand) in izip(valid_upstr_order, chi_integrand):
            dstr_node = receivers[node]
            chi_array[node] = chi_array[dstr_node] + integrand
        chi_array *= mean_dx

    def integrate_chi_each_dx(self, valid_upstr_order, chi_integrand_at_nodes,
                              chi_array):
        """
        Calculates chi at each channel node by summing chi_integrand*dx.

        This method accounts explicitly for spacing between each node. Method
        is deliberately split out for potential cythonization at a later
        stage. Uses a trapezium integration method.

        Parameters
        ----------
        valid_upstr_order : array of ints
            nodes in the channel network in upstream order.
        chi_integrand_at_nodes : array of floats
            The value (A0/A)**concavity, in *node* order.
        chi_array : array of floats
            Array in which to store chi.

        Examples
        --------
        >>> import numpy as np
        >>> from landlab import RasterModelGrid, CLOSED_BOUNDARY
        >>> from landlab.components import FlowRouter
        >>> mg = RasterModelGrid((5,4), 3.)
        >>> for nodes in (mg.nodes_at_right_edge, mg.nodes_at_bottom_edge,
        ...               mg.nodes_at_top_edge):
        ...     mg.status_at_node[nodes] = CLOSED_BOUNDARY
        >>> z = mg.node_x.copy()
        >>> z[[5, 13]] = z[6]  # guard nodes
        >>> _ = mg.add_field('node', 'topographic__elevation', z)
        >>> fr = FlowRouter(mg)
        >>> cf = ChiFinder(mg)
        >>> _ = fr.route_flow()
        >>> ch_nodes = np.array([4, 8, 12, 5, 9, 13, 6, 10, 14])
        >>> ch_integrand = 2.*np.ones(mg.number_of_nodes,
        ...                           dtype=float)  # to make calc clearer
        >>> chi_array = np.zeros(mg.number_of_nodes, dtype=float)
        >>> cf.integrate_chi_each_dx(ch_nodes, ch_integrand, chi_array)
        >>> chi_array.reshape((5,4))
        array([[  0.        ,   0.        ,   0.        ,   0.        ],
               [  0.        ,   6.        ,  14.48528137,   0.        ],
               [  0.        ,   6.        ,  12.        ,   0.        ],
               [  0.        ,   6.        ,  14.48528137,   0.        ],
               [  0.        ,   0.        ,   0.        ,   0.        ]])


        >>> from landlab.components import FastscapeEroder
        >>> mg2 = RasterModelGrid((5, 5), 100.)
        >>> for nodes in (mg2.nodes_at_right_edge, mg2.nodes_at_bottom_edge,
        ...               mg2.nodes_at_top_edge):
        ...     mg2.status_at_node[nodes] = CLOSED_BOUNDARY
        >>> _ = mg2.add_zeros('node', 'topographic__elevation')
        >>> mg2.at_node['topographic__elevation'][mg2.core_nodes] = mg2.node_x[
        ...     mg2.core_nodes]/1000.
        >>> np.random.seed(0)
        >>> mg2.at_node['topographic__elevation'][
        ...     mg2.core_nodes] += np.random.rand(mg2.number_of_core_nodes)
        >>> fr2 = FlowRouter(mg2)
        >>> sp2 = FastscapeEroder(mg2, K_sp=0.01)
        >>> cf2 = ChiFinder(mg2, min_drainage_area=1., reference_concavity=0.5,
        ...                 use_true_dx=True)
        >>> for i in range(10):
        ...     mg2.at_node['topographic__elevation'][mg2.core_nodes] += 10.
        ...     _ = fr2.route_flow()
        ...     sp2.run_one_timestep(1000.)
        >>> _ = fr2.route_flow()
        >>> output_array = np.zeros(25, dtype=float)
        >>> cf2.integrate_chi_each_dx(mg2.at_node['upstream_node_order'],
        ...                           np.ones(25, dtype=float),
        ...                           output_array)
        >>> output_array.reshape((5, 5))
        array([[   0. ,    0. ,    0.        ,    0.        ,    0. ],
               [   0. ,  100. ,  200.        ,  382.84271247,    0. ],
               [   0. ,  100. ,  241.42135624,  341.42135624,    0. ],
               [   0. ,  100. ,  200.        ,  300.        ,    0. ],
               [   0. ,    0. ,    0.        ,    0.        ,    0. ]])
        """
        receivers = self.grid.at_node['flow_receiver']
        links = self.grid.at_node['links_to_flow_receiver']
        link_lengths = self.grid.link_length
        # because chi_array is all zeros, BC cases where node is receiver
        # resolve themselves
        half_integrand = 0.5 * chi_integrand_at_nodes
        for node in valid_upstr_order:
            dstr_node = receivers[node]
            dstr_link = links[node]
            if dstr_link != BAD_INDEX_VALUE:
                dstr_length = link_lengths[dstr_link]
                half_head_val = half_integrand[node]
                half_tail_val = half_integrand[dstr_node]
                mean_val = half_head_val + half_tail_val
                chi_to_add = mean_val * dstr_length
                chi_array[node] = chi_array[dstr_node] + chi_to_add

    def mean_channel_node_spacing(self, ch_nodes):
        """
        Calculates the mean spacing between all adjacent channel nodes.

        Parameters
        ----------
        ch_nodes : array of ints
            The nodes within the defined channel network.

        Returns
        -------
        mean_spacing : float (m)
            The mean spacing between all nodes in the network.

        Examples
        --------
        >>> import numpy as np
        >>> from landlab import RasterModelGrid, CLOSED_BOUNDARY
        >>> from landlab.components import FlowRouter
        >>> mg = RasterModelGrid((5,4), 2.)
        >>> for nodes in (mg.nodes_at_right_edge, mg.nodes_at_bottom_edge,
        ...               mg.nodes_at_top_edge):
        ...     mg.status_at_node[nodes] = CLOSED_BOUNDARY
        >>> z = mg.node_x.copy()
        >>> z[[5, 13]] = z[6]  # guard nodes
        >>> _ = mg.add_field('node', 'topographic__elevation', z)
        >>> fr = FlowRouter(mg)
        >>> cf = ChiFinder(mg)
        >>> _ = fr.route_flow()
        >>> ch_nodes = np.array([4, 8, 12, 5, 9, 13, 6, 10, 14])
        >>> cf.mean_channel_node_spacing(ch_nodes)
        2.2761423749153966
        """
        ch_links = self.grid.at_node['links_to_flow_receiver'][ch_nodes]
        ch_links_valid = ch_links[ch_links != BAD_INDEX_VALUE]
        valid_link_lengths = self.grid.link_length[ch_links_valid]
        return valid_link_lengths.mean()

    @property
    def chi_indices(self):
        """
        Return the array of channel steepness indices.
        Nodes not in the channel receive zeros.
        """
        return self.chi

    @property
    def hillslope_mask(self):
        """
        Return a boolean array, False where steepness indices exist.
        """
        return self._mask
