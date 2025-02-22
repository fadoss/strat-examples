#!/usr/bin/env python3
#
# APMaude simulator
#

import os
import sys

import maude


class APMaudePrettyPrinter:
	"""Print APMaude configurations in a readable format"""

	TTY_MODE = os.isatty(sys.stdout.fileno())
	NUMBER_FORMAT = '\x1b[32m{:.3}\x1b[0m' if TTY_MODE else '{}'
	CHANGED_NUMBER_FORMAT = '\x1b[1;93m{:.3}\x1b[0m' if TTY_MODE else '{}'
	CHANGE_FORMAT = '\x1b[1;93m{}\x1b[0m' if TTY_MODE else '=> {}'

	def __init__(self, module):
		# Find predefined sorts in object-oriented modules
		conf_kind = module.findSort('Configuration').kind()
		float_kind = module.findSort('Float').kind()
		oid_kind = module.findSort('Oid').kind()
		cid_kind = module.findSort('Cid').kind()
		attrs_kind = module.findSort('AttributeSet').kind()

		# Find the entities of the actor PMaude configuration
		self.glue_sym = module.findSymbol('__', (conf_kind, conf_kind), conf_kind)
		self.time_sym = module.findSymbol('time', (float_kind,), conf_kind)
		self.sched_sym = module.findSymbol('[_,_]', (float_kind, conf_kind), conf_kind)
		self.obj_sym = module.findSymbol('<_:_|_>', (oid_kind, cid_kind, attrs_kind), conf_kind)

		# Last term printed for diffing
		self.last_term = None
		# Last time
		self.last_time = None

	def _iter_configuration(self, term):
		"""Return an iterator the arguments of a configuration"""
		return term.arguments() if term.symbol() == self.glue_sym else (term,)

	def _index_term(self, term):
		"""Index objects of a term"""

		# Map from object identifiers to (the whole object term, whether it is scheduled)
		index = {}

		for obj in self._iter_configuration(term):
			match obj.symbol():
				# Object
				case self.obj_sym:
					# Its first argument is the object identifier
					index[next(obj.arguments())] = (obj, False)

				# Scheduled entity
				case self.sched_sym:
					tm, nested = obj.arguments()

					# Do the same with the nested object
					if nested.symbol() == self.obj_sym:
						index[next(nested.arguments())] = (nested, True)

		return index

	def _diff_object(self, old_obj, obj):
		"""Format differences in object attributes"""

		oid, cid, attrs = obj.arguments()
		_, _, old_attrs = old_obj.arguments()

		# _,_ is the only expected binary symbol
		if old_attrs.symbol().arity() == 2:
			old_attrs = set(old_attrs.arguments())
		else:
			old_attrs = {old_attrs}

		# New attributes with highlighting
		new_attrs = ', '.join(
			self.CHANGE_FORMAT.format(attr) if attr not in old_attrs else str(attr)
			for attr in (attrs.arguments() if attrs.symbol().arity() == 2 else (attrs,))
		)

		return f'< {oid} : {cid} | {new_attrs} >'

	def __call__(self, term, time_step=False):
		# Lines in the output
		lines = []

		# Initial line jump if there should be no time
		if not time_step:
			lines.append('')

		# Set of configuration entities in the old configuration
		old_objects = set(self.last_term.arguments()) if self.last_term else ()
		# Index of objects in the old configuration
		old_index = self._index_term(self.last_term) if self.last_term else {}

		for obj in self._iter_configuration(term):
			match obj.symbol():
				# Time symbol
				case self.time_sym:
					self.last_time = float(next(obj.arguments()))
					# Ignored if not a time step, otherwise shown in the first place
					if time_step:
						lines.insert(0, self.NUMBER_FORMAT.format(self.last_time))

				# Scheduled entity
				case self.sched_sym:
					# Scheduled entity
					delay, msg = obj.arguments()

					# New or modified scheduled entity
					if self.last_term and obj not in old_objects:
						# The scheduled entity is new
						if msg not in old_objects:
							timestamp = self.NUMBER_FORMAT.format(float(delay))
							entity = self.CHANGE_FORMAT.format(msg)
						# The scheduled entity was in the configuration, but not scheduled
						else:
							timestamp = self.CHANGED_NUMBER_FORMAT.format(float(delay))
							entity = msg

						lines.append(f'[{timestamp}, {entity}]')

					else:
						lines.append('[{}, {}]'.format(self.NUMBER_FORMAT.format(float(delay)), msg))

				# Object
				case self.obj_sym:
					# This object is new or has been modified
					if self.last_term and obj not in old_objects:
						oid = next(obj.arguments())  # its object identifier
						old_obj, is_nested = old_index.get(oid, (None, True))

						lines.append(self.CHANGE_FORMAT.format(obj) if is_nested
						             else self._diff_object(old_obj, obj))
					else:
						lines.append(str(obj))

				case _:
					lines.append(str(obj) if obj in old_objects
					             else self.CHANGE_FORMAT.format(obj))

		self.last_term = term
		return '\n┆  '.join(lines)


def simulate(initial, steps=3, time=(0, float('inf'))):
	"""Simulate a APMaude specification"""

	# Module to simulate
	module = initial.symbol().getModule()
	# Probabilistic or ordinary step
	pm_all = module.parseStrategy('pm-all')

	# Time range
	t0, t1 = time

	# Configuration printer
	printer = APMaudePrettyPrinter(module)

	# Simulate the PMaude environment
	t = initial
	t.reduce()

	for _ in range(steps):
		# Initial term at a given time
		pretty_term = printer(t, time_step=True)

		# Ensure that only the selected period of time is shown
		if printer.last_time > t1:
			break

		if printer.last_time >= t0:
			print('┣━━━ ⏰', pretty_term)

		while True:
			successors = list(t.srewrite(pm_all))

			# No more rules applicable without a tick
			if len(successors) == 0:
				break

			else:
				t, _ = successors[0]

				if len(successors) > 1:
					print(f'⚠️ The APMaude specification is not deterministic ({len(successors)} different successors).')

			# Term after a rewrite that does not advance the clock
			if printer.last_time >= t0:
				print('┠─', printer(t))

		# Advance the clock
		next_t = next(t.apply('tick'), None)

		if next_t is None:
			print('No more steps.')
			break
		else:
			t = next_t[0]
			t.reduce()


def main():
	import argparse

	parser = argparse.ArgumentParser(description='Simulate APMaude specifications')
	parser.add_argument('input', help='Input Maude file')
	parser.add_argument('initial', help='Initial term')
	parser.add_argument('--module', '-m', help='Module to work with')
	parser.add_argument('--steps', '-s', help='Number of steps to simulate', type=int, default=3)
	parser.add_argument('--time', '-t', help='Limit simulation and printing to a period of time')
	parser.add_argument('--seed', help='Random seed', type=int)

	args = parser.parse_args()

	# Initialize Maude and load the given file
	maude.init()

	if not maude.load(args.input):
		print('Error reading input file.')
		return 1

	initial_module = maude.getCurrentModule()

	if (aptrans := maude.getModule('APMAUDE-TRANSLATE')) is None:
		print('Error: APMaude modules are not loaded. Is this an APMuade specification?')
		return 1

	# Name of the module to work with
	module_name = args.module if args.module else str(initial_module)

	if args.module and maude.getModule(args.module) is None:
		print(f'Error: module {args.module} does not exist')
		return 1

	# Obtain the transformed module
	if (translated_module := aptrans.parseTerm(f"atransform(upModule('{module_name}, true))")) is None:
		print('Error: cannot parse module transformation term.')
		return 1

	translated_module.reduce()

	if not (translated_module.getSort() <= aptrans.findSort('Module')):
		print(f'Error: the transformation does not produce a valid module, its sort is {translated_module.getSort()}.')
		return 1

	# Obtain a module from the metamodule
	if (translated_module := maude.downModule(translated_module)) is None:
		print(f'Error: the transformed module cannot be used.')
		return 1

	# Parse the initial term
	if (initial := translated_module.parseTerm(args.initial)) is None:
		print(f'Error: cannot parse the initial term: {args.initial}.')
		return 1

	# Parse the time range
	t0, t1 = 0, float('inf')

	if args.time:
		if ':' in args.time:
			t0, t1 = map(float, args.time.split(':'))
		else:
			t1 = float(args.time)

	# Sets the random seed
	if args.seed is not None:
		maude.setRandomSeed(args.seed)

	simulate(initial, steps=args.steps, time=(t0, t1))

	return 0


if __name__ == '__main__':
	sys.exit(main())
