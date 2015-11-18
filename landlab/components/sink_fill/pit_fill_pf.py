"""
pit_fill_pf.py
Priority-Flood algorithm (Barnes et al. 2014)

Created by JL, Nov. 2015
"""
import numpy as np

import Queue

import landlab
from landlab import Component, FieldError
from landlab.grid.base import BAD_INDEX_VALUE

class PitFiller(Component):

    def __init__(self, input_grid):

        self._grid = input_grid
        self._dem = self._grid.at_node['topographic__elevation'].copy()
        self._n = self._grid.number_of_nodes
        (self._boundary, ) = np.where(self._grid.status_at_node!=0)
        (self._open_boundary, ) = np.where(np.logical_or(self._grid.status_at_node==1, self._grid.status_at_node==2))

        self._neighbors = np.concatenate((self._grid.neighbors_at_node, self._grid.diagonals_at_node), axis=1)
        self._neighbors[self._neighbors == BAD_INDEX_VALUE] = -1


    def pit_fill(self):

        closed = np.zeros(self._n, dtype=bool)
        raised_node = Queue.Queue(maxsize=self._n)
        priority_queue = Queue.PriorityQueue(maxsize=self._n)

        raised_put = raised_node.put
        raised_get = raised_node.get
        priority_put = priority_queue.put
        priority_get = priority_queue.get
        raised_empty = raised_node.empty
        priority_empty = priority_queue.empty

        for i in self._open_boundary:
            priority_put((self._dem[i], i))
            closed[i] = True

        while not(raised_empty()) or not(priority_empty()):
            if not(raised_empty()):
                node = raised_get()
            else:
                elev, node = priority_get()
            for neighbor_node in self._neighbors[node]:
                if neighbor_node==-1:
                    continue
                if closed[neighbor_node]:
                    continue
                closed[neighbor_node] = True
                if self._dem[neighbor_node]<=self._dem[node]:
                    self._dem[neighbor_node] = self._dem[node]
                    raised_put(neighbor_node)
                else:
                    priority_put((self._dem[neighbor_node], neighbor_node))

        self._grid.at_node['topographic__elevation'] = self._dem
        return self._grid
