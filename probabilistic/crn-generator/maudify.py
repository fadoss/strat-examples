#!/usr/bin/env python3
#
# Maudify (and C-ify) CRNs from an input file of the SeQuaiA tool
#
# The resulting programs compute abstractions of chemical reaction networks
# by simulation, as in the SeQuaiA tool (https://sequaia.model.in.tum.de/),
# but they can also be used to simulate CRNs in other ways.
#
# The simulation strategy and part of this code is based on the algorithm
# for computing abstractions by Martin Helfrich, integrated into that tool.
#


import argparse
import json
import os
import sys
from fractions import Fraction

from jinja2 import Environment, FileSystemLoader, StrictUndefined


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


class CRNTranslator:
	"""Base class of the translators from a CRN specification"""

	def __init__(self, crn, levels, init, ofile=sys.stdout, name='CRN', use_time=False,
	             acceleration=0, num_simulations=100, boundary='abs'):

		self.name = name
		self.crn = crn
		self.levels = levels
		self.init = init
		self.ofile = ofile

		self.use_time = use_time
		self.accelerate_every = acceleration
		self.num_simulations = num_simulations
		self.boundary = boundary

	@staticmethod
	def extended_axis(axis):
		"""Axis extended to the center of the neightbors"""

		return ([axis[0]]
		        + [(axis[i-1] + axis[i]) // 2 for i in range(1, len(axis))]
		        + [axis[-1]])

	@property
	def extended_limits(self):
		"""Limits extended to the center of the neighbors"""

		return [self.extended_axis(axis) for axis in self.levels]

	@property
	def accelerated(self):
		"""Whether the simulation is accelerated"""

		return self.accelerate_every > 0

	@property
	def initial_abstract_state(self):
		"""The abstract state where the simulation starts"""

		return tuple(max((index for index, y in enumerate(self.levels[k]) if y <= x))
		             for k, x in enumerate(self.init))


class CTranslator(CRNTranslator):
	"""Convert CRN specification to C"""

	def __init__(self, jinja_env, *args, cpp=False, **kwargs):
		super().__init__(*args, **kwargs)

		self.template = jinja_env.get_template('crnsim.cc.jinja' if cpp else 'crnsim.c.jinja')

	@staticmethod
	def make_factor(var, mult):
		"""Make a factor with potential multiplicities"""

		return ' * '.join([var] + [f'{var} - {m}' for m in range(1, mult)])

	@property
	def max_axis_length(self):
		"""Length of the largest axis of the levels"""

		return max(map(len, self.levels))

	def species_repeat(self, tmpl, junc=', '):
		"""Repeat a format string and fill it with the indices of the species"""

		return junc.join((tmpl.format(n) for n in range(self.crn.d)))

	def make_propensity(self, reaction):
		"""Make a expression for the propensity of a reaction"""

		prop = ' * '.join((self.make_factor(f'species[{k}]', m) for k, m in enumerate(reaction.pre) if m > 0))

		return f'{reaction.rate} * {prop}'

	def make_outside_check(self):
		"""Make a Boolean expression to check whether the indices are outside the levels region"""

		return ' || '.join((f'indices[{k}] + j{k} >= {len(level) - 1}' for k, level in enumerate(self.levels)))

	def to_c(self):
		"""Translate the CRN specification to C or C++"""

		return self.template.render(
			gen=self,
			# Additional names for readability of the template
			name=self.name,
			crn=self.crn,
			num_species=self.crn.d,
			num_reactions=len(self.crn.reactions)
		)


class Maudifier(CRNTranslator):
	"""Convert CRN specification to a Maude file"""

	def __init__(self, jinja_env, *args, metadata=True, **kwargs):
		super().__init__(*args, **kwargs)

		self.metadata = metadata

		self.rule_labels = self.make_readable_labels()
		self.propensities = self.make_propensities()

		self.template = jinja_env.get_template('crnsim.maude.jinja')

	@property
	def species_vars(self, extra=()):
		"""Produce the species variable names for the CRN"""

		return [s.capitalize() for s in self.crn.species] + list(extra)

	def make_readable_labels(self):
		"""Produce readable names for the reactions"""

		labels = []

		for reaction in self.crn.reactions:
			label = '_'.join([self.crn.species[k] for k, m in enumerate(reaction.pre) if m > 0])

			if label in labels:
				k = 2
				while f'{label}{k}' in labels:
					k = k + 1
				label = f'{label}{k}'

			labels.append(label)

		return labels

	def make_tuple_pattern(self, tupl, extra=()):
		"""Produce a tuple pattern for the rules"""

		args = []

		for k, value in enumerate(tupl):
			arg = self.crn.species[k].capitalize()

			if value == 1:
				arg = 's ' + arg

			elif value > 1:
				arg = f's_^{value}({arg})'

			args.append(arg)

		args += extra

		return '< ' + ', '.join(args) + ' >'

	@staticmethod
	def make_literal_tuple(tupl, extra=()):
		"""Make a tuple of literals"""

		return '< ' + ', '.join(list(map(str, tupl)) + list(extra)) + ' >'

	def make_rules(self):
		"""Make the rules of the module"""

		width = max(map(len, self.rule_labels)) + 1

		for k, r in enumerate(self.crn.reactions):
			lhs = self.make_tuple_pattern(r.pre, extra=['T'] if self.use_time else ())
			rhs = self.make_tuple_pattern(r.post, extra=['T'] if self.use_time else ())
			lbl = self.rule_labels[k]  # f'r{k}'

			metaprop = f'[metadata "{r.rate}"] ' if self.metadata else ''

			yield f'rl [{lbl + "]":{width}} : {lhs} => {rhs} {metaprop}.'

	@staticmethod
	def make_factor(var, mult):
		"""Make a factor with multiplicities"""

		return ' * '.join([var] + [f'sd({var}, {m})' for m in range(1, mult)])

	def make_propensity_int(self, reaction):
		"""Make the propensity of a reaction (integer version, not used now)"""

		prop = ' * '.join((self.make_factor(self.crn.species[k].capitalize(), m)
		                   for k, m in enumerate(reaction.pre) if m > 0))

		num, den = Fraction(float(reaction.rate)).limit_denominator().as_integer_ratio()

		if num != 1:
			prop = f'{num} * {prop}'

		if den != 1:
			prop = f'({prop}) quo {den}'

		return prop

	def make_propensity(self, reaction):
		"""Make the propensity of a reaction"""

		# A memo operator could be used to memorize these products
		prop = ' * '.join((self.make_factor(self.crn.species[k].capitalize(), m)
		                   for k, m in enumerate(reaction.pre) if m > 0))

		return prop if reaction.rate == 1 else (
		       f'{int(reaction.rate)} * {prop}' if reaction.rate.is_integer() else
		       f'{reaction.rate} * float({prop})')

	def make_propensities(self):
		"""Make the propensities of all reactions in the CRN"""

		return [self.make_propensity(self.crn.reactions[k]) for k in range(len(self.rule_labels))]

	def propensities_sum(self):
		"""Make the sum of all propensities"""

		prop_float = [p if '.' in p or 'float' in p else f'float({p})' for p in self.propensities]

		return ' + '.join(prop_float)

	@staticmethod
	def choice_action(lbl, accelerated):
		"""The action executed by choice, which may be accelerated or not"""

		return lbl.replace('_', '-') + '-repeat(N)' if accelerated else lbl

	def write_choice(self, accelerated=False):
		"""Write the choice operator for the CRN"""

		# For aesthetic reasons, propensities are calculated first
		width = max(map(len, self.propensities))

		return [f'{self.propensities[k]:{width}} : {self.choice_action(lbl, accelerated)}'
		        for k, lbl in enumerate(self.rule_labels)]

	def write_repeat_rule(self):
		"""Write declaration and definitions of strategies that repeat the execution of rules"""

		lines = []

		# Strategy names for the repetition
		names = [f'{rl.replace("_", "-")}-repeat' for rl in self.rule_labels]

		# Strategy declarations
		lines.append('strats ' + ' '.join(names) + ' : Nat @ System .\n')

		# Strategy definitions
		for k, name in enumerate(names):
			lines.append(f'sd {name}(0) := idle .')
			lines.append(f'sd {name}(s N) := {self.rule_labels[k]} ; {name}(N) .')

		return '\n\t'.join(lines)

	@property
	def variable_pattern(self):
		"""Make a only-variable pattern"""

		return self.make_tuple_pattern((0,) * self. crn.d, extra=('T', ) if self.use_time else ())

	def make_bound_equation(self):
		"""Make the equation that checks the exploration bounds"""

		bound_pattern = ', '.join([f'[L{v}:Nat, U{v}:Nat]' for v in self.species_vars])
		condition = ' and-then '.join((f'L{v}:Nat <= {v} and-then {v} < U{v}:Nat' for v in self.species_vars))

		return f'withinBounds({self.variable_pattern}, boundary({bound_pattern})) = {condition}'

	def to_maude(self):
		"""Produce a Maude specification of the CRN"""

		return self.template.render(
			gen=self,
			# Additional names for readability of the template
			name=self.name,
			crn=self.crn,
			num_species=self.crn.d,
			num_reactions=len(self.crn.reactions)
		)


def translate_crn(crn, levels, init, c=False, cpp=False, **kwargs):
	"""Translate the given CRN to a Maude/C/C++ program"""

	# Load and set up the Jinja environment
	env = Environment(loader=FileSystemLoader('templates'), trim_blocks=True, lstrip_blocks=True)
	env.filters['repeat'] = lambda s, n, d=' ': d.join([s] * n)
	env.undefined = StrictUndefined

	if c or cpp:
		ctr = CTranslator(env, crn, levels, init, cpp=cpp, **kwargs)
		return ctr.to_c()
	else:
		mdf = Maudifier(env, crn, levels, init, **kwargs)
		return mdf.to_maude()


if __name__ == '__main__':

	parser = argparse.ArgumentParser(description='Convert SeQuaiA models to Maude')
	parser.add_argument('model', help='SeQuaiA source file')
	parser.add_argument('--no-time', help='Calculate time', dest='time', action='store_false')
	parser.add_argument('-c', help='Translate to C instead of Maude', action='store_true')
	parser.add_argument('-c++', help='Translate to C++ instead of Maude', dest='cpp', action='store_true')

	# Parameters of the original setting
	parser.add_argument("-a", "--simulation_accelerate_every", type=int, default=100,
	                    help='duplicate speed every the given number of iterations')
	parser.add_argument("-l", "--limit2abs", dest='limit2abs', action='store_true',
	                    help='consider that the abstract state is escaped without extended boundaries')
	parser.add_argument("-sims", "--simulations_per_abstract_state", type=int, default=100,
	                    help='simulations per abstract state')

	args = parser.parse_args()

	# Pass the configuration from the input arguments to the translators
	config = {
		'name'            : os.path.basename(args.model),
		'use_time'        : args.time,
		'acceleration'    : args.simulation_accelerate_every,
		'num_simulations' : args.simulations_per_abstract_state,
		'boundary'        : 'abs' if args.limit2abs else 'extended'
	}

	print(translate_crn(*from_sequaia_json(args.model), c=args.c, cpp=args.cpp, **config))

