#!/usr/bin/env python3
#
# Run the simulation of the Maude specification of a CRN generated by
# maudify.py and produce an abstraction as in the SeQuaiA tool
# (https://sequaia.model.in.tum.de/).
#
# The simulation strategy and part of this code is based on the algorithm
# for computing abstractions by Martin Helfrich, integrated into SeQuaiA.
#

import argparse
import itertools
import json
import math
import os
import random
import shutil
import subprocess

from collections import Counter
from multiprocessing import Pool
from os import cpu_count, environ
from tempfile import NamedTemporaryFile
from time import time_ns


# ∨∨∨∨ Copied from Abstraction/CRN/mainSim.py

class CRN:
	"""Chemical reaction network (copied from CRN.py)"""

	def __init__(self, name, species, reactions, initial):
		self.d = len(species)  # list of species names
		self.species = list(species)
		self.name = name  # name of CRN
		self.reactions = reactions  # list of reactions
		initial = list(initial)  # list of values
		self.initial = initial

	def __repr__(self):
		return f'CRN({self.name}, initial={self.initial}, reactions=[{", ".join([str(r) for r in self.reactions])}])'


class Reaction:
	"""Chemical reaction (copied from CRN.py)"""

	def __init__(self, name, rate, reactants, products):
		self.d = len(reactants)
		self.name = name
		self.rate = rate
		self.pre = list(reactants)  # list of required reactant quantities (non-negative values)
		self.post = list(products)  # list of product quantities (non-negative values)
		self.effect = [-self.pre[i] + self.post[i] for i in range(self.d)]  # effect on the multiset

	def __repr__(self):
		return f'Reaction({self.name}, rate={self.rate}, pre={self.pre}, post={self.post})'


class Abstraction:
	"""Abstraction of a chemical reaction network (copied from Abstraction.py)"""

	def __init__(self, levels, initial_state=None):
		self.d = len(levels)
		self.levels = levels
		self.abstract_states = {}
		self.transitions_from = {}
		self.transitions = set()
		for loc in itertools.product(*((i for i in range(len(ls) - 1)) for ls in levels)):
			a_s = AbstractState(loc, self)
			a_s.is_initial = initial_state and a_s.contains_state(initial_state)
			self.add_abstract_state(a_s)

		self.add_abstract_state(AbstractState((-1, ) * self.d, self))   # out of bounds

	def add_abstract_state(self, a_s):
		if a_s.loc not in self.abstract_states:
			self.abstract_states[a_s.loc] = a_s
			self.transitions_from[a_s.loc] = {}

	def add_transition(self, transition):
		self.transitions_from[transition.start.loc][transition.end.loc] = transition
		self.transitions.add(transition)


class AbstractState:
	"""State of the CRN abstraction (copied from Abstraction.py)"""

	def __init__(self, loc, abstraction, initial=False):
		self.abstraction = abstraction
		self.d = self.abstraction.d
		self.is_initial = initial
		self.loc = loc
		self.min = [self.abstraction.levels[i][loc[i]] for i in range(self.d)]  # included
		self.max = [self.abstraction.levels[i][loc[i] + 1] for i in range(self.d)]  # excluded
		representative_without_rounding = [(self.min[i] + self.max[i] - 1) / 2 for i in range(self.d)]
		self.representative = [int(representative_without_rounding[i]) for i in range(self.d)]
		self.isErrorState = any((x == -1 for x in self.loc))

	def neighbor_in_dir(self, dir):
		loc_neighbor = tuple(self.loc[i] + dir[i] for i in range(self.d))
		neighbor = self.abstraction.abstract_states.get(loc_neighbor)
		if neighbor is not None:
			return neighbor
		return self.abstraction.abstract_states[(-1, ) * self.d]

	def contains_state(self, state):
		return all((self.min[i] <= state[i] < self.max[i] for i in range(self.d)))

	def __repr__(self):
		return f'AbstractState(representative={self.representative}, min={self.min},' \
		       f' max={self.max}, initial={self.is_initial})'


def from_sequaia_json(file):
	"""Read a SeQuaiA model file (copied from mainSim.py)"""

	with open(file) as json_file:
		data = json.load(json_file)
		initial = data['init']
		d = data['dimension']
		reactions = [Reaction(r['label'], r['rate'], [-v for v in r['reactant']],
			                  [v for v in r['product']]) for r in data['reactions']]
		crn = CRN(data['name'], data['speciesNames'], reactions, initial)

		levels = [[0, 1] + [x + 1 for x in data['discretization'][i]] + [data['bound'][i]+1] for i in range(d)]

		return crn, levels, initial

# ∧∧∧∧ Copied from Abstraction/CRN/mainSim.py


def _simulation(mfile, initial, strategy, nexec, seed):
	"""Run a simulation a number of times (in a separate process)"""

	if seed is not None:
		environ['CHOICE_SEED'] = str(seed)

	import maude

	maude.init()
	maude.load(mfile)
	m = maude.getCurrentModule()
	t = m.parseTerm(initial)
	s = m.parseStrategy(strategy)

	acc_sols = Counter()
	nrew_sum = 0

	for i in range(nexec):
		for sol, nrew in t.srewrite(s):
			acc_sols[str(sol)] += 1
			nrew_sum += nrew

	return acc_sols, nrew_sum


class PslSimulator:
	"""Simulator for the probabilistic strategy language"""

	def __init__(self, mfile, initial, strategy, nproc=cpu_count(), nexec=10):
		# Problem data
		self.mfile = mfile
		self.initial = initial
		self.strategy = strategy

		# Simulation parameters
		self.nproc = nproc
		self.nexec = nexec

		# Results
		self.results = Counter()
		self.nrew = 0
		self.stime = 0

	def simulate(self, seed=None):
		"""Simulate using multiples processes"""

		# Set the random seed of the Maude processed with
		# random numbers produced here
		if seed is not None:
			random.seed(seed)

		# Run multiple processes in parallel
		init_time = time_ns()

		with Pool(self.nproc) as p:
			outcome = p.starmap(_simulation, [(self.mfile, self.initial, self.strategy, self.nexec,
			                                   random.randrange(int(1e6))
			                                   if seed is not None else None)] * self.nproc)
		end_time = time_ns()

		# Add the result to the global accumulator
		for res, nrew in outcome:
			self.results += res
			self.nrew += nrew

		self.stime += (end_time - init_time)

	def print_summary(self):
		"""Print a summary of the simulation results"""

		# Total number of simulations
		num_sim = sum(self.results.values())

		print('Simulation finished after', num_sim, 'executions,',
		      self.nrew, 'rewrites and',
		      int(self.stime // 1e6), 'ms:\n')

		# The probability of each output in decreasing order
		for term, times in self.results.most_common():
			print(f'\t{term}\t\t{times / num_sim}')

		print()


class SeqSimulator:
	"""Sequential simulator for the probabilistic strategy language"""

	maude = None

	def __init__(self, mfile, nexec=10):
		# Problem data
		self.mfile = mfile

		if self.maude is None:
			import maude
			self.maude = maude
			maude.init()

		maude.load(mfile)

		self.m = maude.getCurrentModule()

		# Simulation parameters
		self.nexec = nexec

		# Results
		self.results = Counter()
		self.nrew = 0
		self.stime = 0

	def simulate(self, initial, strategy, seed=None):
		"""Single-threaded simulation"""

		# Set the random seed
		if seed is not None:
			random.seed(seed)

		t = self.m.parseTerm(initial)
		s = self.	m.parseStrategy(strategy)

		self.results = Counter()
		self.nrew = 0

		for i in range(self.nexec):
			for sol, nrew in t.srewrite(s):
				self.results[str(sol)] += 1
				self.nrew += nrew


class CRNSimulator:
	"""Simulator of CRNs in Maude"""

	def __init__(self, crn, levels, init, mfile, num_simulations=100, boundary='extended', simaude=None, jobs=None, **_):
		self.crn = crn
		self.levels = levels
		self.init = init
		self.mfile = mfile
		self.jobs = cpu_count() if jobs is None else jobs
		self.simaude = simaude

		self.num_simulations = num_simulations
		self.boundary = boundary

		self.seqsim = SeqSimulator(mfile, nexec=num_simulations) if jobs == 1 else None

		# Extended limits to the center of the neighbor
		self.extended_limits = [[axis[0]] + [(axis[i-1] + axis[i]) // 2 for i in range(1, len(axis))]
		                        + [axis[-1]] for axis in self.levels]

	def make_boundary(self, pos):
		"""Make exploration boundaries"""

		if self.boundary == 'extended':
			intervals = [f'[{self.extended_limits[axis][index]}, {self.extended_limits[axis][index+2]}]'
			             for axis, index in enumerate(pos)]
		else:
			intervals = [f'[{self.levels[axis][index]}, {self.levels[axis][index+1]}]' for axis, index in enumerate(pos)]

		return 'boundary(' + ', '.join(intervals) + ')'

	def process_results(self, astate, result):
		"""Process the results of the simulation"""

		successors = {}

		# Total hits
		total_hits = sum(result.values())

		for tup, hits in result.items():
			*rpos, time = tup.lstrip('< ').rstrip(' >').split(',')

			time = float(time)
			rpos = tuple(map(int, rpos))

			roffset = tuple(
				      1 if rpos[i] >= astate.max[i]
				else -1 if rpos[i] < astate.min[i]
				else  0
				        for i in range(self.crn.d)
			)

			pos = astate.neighbor_in_dir(roffset).loc

			if (previous_entry := successors.get(pos)) is not None:
				successors[pos] = (hits + previous_entry[0], time + previous_entry[1])

			else:
				successors[pos] = (hits, time)

		for suc, (hits, time) in successors.items():
			if suc != astate.loc:
				print(f'{astate.loc};{suc};{hits / total_hits};{time / hits}')

	def run(self):
		# create abstraction (without transitions)
		abstraction = Abstraction(self.levels, initial_state=self.init)

		print(self.levels)
		print([state.loc for state in abstraction.abstract_states.values() if state.is_initial][0])
		print('start;end;p;ex_time')

		for pos, astate in abstraction.abstract_states.items():
			if astate.isErrorState:
				continue

			initial = '< ' + ', '.join(map(str, astate.representative)) + ', 0.0 >'
			strategy = f'simulate(0, 1, {self.make_boundary(pos)})'

			if self.simaude is not None:
				smr = subprocess.run([self.simaude, '-n', str(self.num_simulations), '-j', str(self.jobs),
				                      self.mfile, initial, strategy],
				                     stdout=subprocess.PIPE)

				results = {term.decode('utf-8'): float(p) for term, p in
				           [line.strip().split(b'\t') for line in smr.stdout.split(b'\n')[2:-1]]}

			elif self.jobs > 1:
				# We are doing more simulations depending if the number of cores
				# does not divide the number of simulations just for symetry.
				sim_per_process = math.ceil(self.num_simulations / self.jobs)

				# This is not very efficient because we are reloading the Maude file every time
				sim = PslSimulator(self.mfile, initial, strategy, nproc=cpu_count(), nexec=sim_per_process)
				sim.simulate()
				results = sim.results

			else:
				self.seqsim.simulate(initial, strategy)
				results = self.seqsim.results

			# print('\x1b[33m>>>', pos, astate, results, '\x1b[0m')

			self.process_results(astate, results)

	def _simaude(self, pos, astate):
		initial = '< ' + ', '.join(map(str, astate.representative)) + ', 0.0 >'
		strategy = f'simulate(0, 1, {self.make_boundary(pos)})'

		smr = subprocess.run([self.simaude, '-j', str(self.jobs), self.mfile, initial, strategy],
		                     stdout=subprocess.PIPE)

		results = {term.decode('utf-8'): float(p) for term, p in
		           [line.strip().split(b'\t') for line in smr.stdout.split(b'\n')[2:-1]]}

		self.process_results(astate, results)

	def run_simaude(self):
		# create abstraction (without transitions)
		abstraction = Abstraction(self.levels, initial_state=self.init)

		from multiprocessing import Pool

		print(self.levels)
		print([state.loc for state in abstraction.abstract_states.values() if state.is_initial][0])
		print('start;end;p;ex_time')

		with Pool(self.jobs) as pool:
			pool.starmap(self._simaude, filter(lambda arg: not arg[1].isErrorState, abstraction.abstract_states.items()))


if __name__ == '__main__':

	parser = argparse.ArgumentParser(description='Convert SeQuaiA models to Maude')
	parser.add_argument('sequaia_model', help='SeQuaiA source file')
	parser.add_argument('maude_file', help='Maude source file (or - to generate it now)')

	# Parameters of the original setting
	parser.add_argument("-a", "--simulation_accelerate_every", type=int, default=100,
	                    help='duplicate speed every the given number of iterations')
	parser.add_argument("-l", "--limit2abs", dest='limit2abs', action='store_true',
	                    help='consider that the abstract state is escaped without extended boundaries')
	parser.add_argument("-sims", "--simulations_per_abstract_state", type=int, default=100,
	                    help='simulations per abstract state')

	parser.add_argument("-j", "--jobs", type=int, default=None,
	                    help='number of parallel simulation jobs')
	parser.add_argument("--simaude", action='store_true',
	                    help='use the simaude program instead of Python to execute the simulation')
	parser.add_argument("--multi-simaude", action='store_true',
	                    help='run in parallel a simaude instance per abstract state')

	args = parser.parse_args()
	ecrn = from_sequaia_json(args.sequaia_model)

	config = {
		'name': os.path.basename(args.sequaia_model),
		'use_time': True,
		'acceleration': args.simulation_accelerate_every,
		'num_simulations': args.simulations_per_abstract_state,
		'boundary': 'abs' if args.limit2abs else 'extended'
	}

	if args.simaude:
		simaude_bin = os.getenv('SIMAUDE_PATH') or shutil.which('simaude')
	else:
		simaude_bin = None

	# If - is passed we generate the Maude specification on the fly
	if args.maude_file == '-':
		from maudify import translate_crn

		with NamedTemporaryFile(suffix='.maude') as tmp_file:
			tmp_file.write(translate_crn(*ecrn, **config).encode('utf-8'))
			tmp_file.flush()

			simulator = CRNSimulator(*ecrn, tmp_file.name, simaude=simaude_bin, jobs=args.jobs, **config)
			if simaude_bin is not None and args.multi_simaude:
				simulator.run_simaude()
			else:
				simulator.run()
	else:
		simulator = CRNSimulator(*ecrn, args.maude_file, simaude=simaude_bin, jobs=args.jobs, **config)
		if simaude_bin is not None and args.multi_simaude:
			simulator.run_simaude()
		else:
			simulator.run()