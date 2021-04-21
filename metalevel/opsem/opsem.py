#!/usr/bin/env python3
#
# Small-step operational semantics of the Maude strategy language
#
# It requires the maude (https://pypi.org/project/maude/) and umaudemc packages.
# The latter is included as a file called umaudemc in the strategy-aware model
# checker downloads. Set PYTHONPATH to the full path of this file to run this.
#


import sys
import maude

from umaudemc.api import MaudeModel
from umaudemc.command.test import read_suite
from umaudemc.formulae import Parser

##
## Operational semantics handling
##

INSTANTIATION = '''view OpSem-{targetmod} from MODULE to META-LEVEL is
	op M to term upModule('{targetmod}, true) .
endv

smod OPSEM-MAIN-{targetmod} is
	protecting NOP-PREDS{{OpSem-{targetmod}}} .
	protecting {semanticsmod}{{OpSem-{targetmod}}} .
	protecting LEXICAL .
	including STRATEGY-MODEL-CHECKER .
endsm'''


class OpSemInstance:
	"""Instance of the operational semantics for a module"""

	def __init__(self, osmod, targetmod):
		# Module of the operational semantics
		self.osmod = osmod
		# Module where terms are rewritten
		self.targetmod = targetmod

		self.load_values()

	def load_values(self):

		# Load sorts required to find symbols in the semantics
		expart_kind    = self.osmod.findSort('ExStatePart').kind()
		exstate_kind   = self.osmod.findSort('ExState').kind()
		stack_kind     = self.osmod.findSort('CtxStack').kind()
		stsoup_kind    = self.osmod.findSort('SubtermSoup').kind()
		subs_kind      = self.osmod.findSort('Substitution').kind()
		condition_kind = self.osmod.findSort('Condition').kind()
		self.term_sort = self.osmod.findSort('Term')
		term_kind      = self.term_sort.kind()
		context_kind   = self.osmod.findSort('Context').kind()
		self.strategy_sort = self.osmod.findSort('Strategy')
		strategy_kind  = self.strategy_sort.kind()

		# Find symbols for decomposing the semantic states
		self.cterm         = self.osmod.findSymbol('cterm', [exstate_kind], term_kind)
		self.subs_unit     = self.osmod.findSymbol('_<-_', [term_kind] * 2, subs_kind)
		self.subterm_unit  = self.osmod.findSymbol('_:_', [term_kind, exstate_kind], stsoup_kind)
		self.eps_symb      = self.osmod.findSymbol('eps', [], stack_kind)
		self.stack_list    = self.osmod.findSymbol('__', [stack_kind] * 2, stack_kind)
		self.ctx_symb      = self.osmod.findSymbol('ctx', [subs_kind], stack_kind)
		self.stack_state   = self.osmod.findSymbol('_@_', [expart_kind, strategy_kind], exstate_kind)
		self.subterm_state = self.osmod.findSymbol('subterm', [stsoup_kind, term_kind], expart_kind)
		self.rewc_state    = self.osmod.findSymbol('rewc', [term_kind, exstate_kind, subs_kind, condition_kind,
		                                                    strategy_kind, stack_kind, term_kind, context_kind,
		                                                    term_kind], expart_kind)

	def print_assignement(self, assg):
		variable, value = assg.arguments()
		return '{}={}'.format(self.print_variable(variable), self.targetmod.downTerm(value))

	def print_substitution(self, subs):
		if subs.symbol() == self.subs_unit:
			return self.print_assignement(subs)
		else:
			return ', '.join([self.print_assignement(assg) for assg in subs.arguments()])

	def print_stack(self, st):
		symbol = st.symbol()

		if symbol == self.stack_list:
			stack_text = []

			for entry in st.arguments():
				stack_text.append(self.print_stack(entry))

			return ' '.join(stack_text)

		elif symbol == self.ctx_symb:
			return 'ctx({})'.format(self.print_substitution(next(st.arguments())))

		elif st.getSort() <= self.strategy_sort:
			return str(self.targetmod.downStrategy(st))

		elif symbol == self.eps_symb:
			return 'ε'

		else:
			return '!! Unknown stack element !!'

	def print_variable(self, variable):
		variable = str(variable)
		return variable[1:variable.index(':')]

	def print_subterm(self, subterms):
		if subterms.symbol() == self.subterm_unit:
			variable, state = subterms.arguments()

			return '{} : {}'.format(self.print_variable(variable), self.print_state(state))
		else:
			subterms_text = []

			for subterm in subterms.arguments():
				variable, state = subterm.arguments()

				subterms_text.append('{} : {}'.format(self.print_variable(variable), self.print_state(state)))

			return ', '.join(subterms_text)

	def print_part(self, xsp):
		symbol = xsp.symbol()

		if xsp.getSort() <= self.term_sort:
			return self.targetmod.downTerm(xsp)

		elif symbol == self.subterm_state:
			substates, pattern = xsp.arguments()

			return 'subterm({}; {})'.format(self.print_subterm(substates), self.targetmod.downTerm(pattern))

		elif symbol == self.rewc_state:
			return 'rewc'

		else:
			return '!! Unknown ExState !!'

	def print_state(self, xst):
		# We assume that they symbol is stack_state
		part, stack = xst.arguments()

		return '{} @ {}'.format(self.print_part(part), self.print_stack(stack))

	def get_cterm(self, xst):
		t = self.cterm(xst)
		t.reduce()
		return self.targetmod.downTerm(t)

	def print_cterm(self, xst):
		return str(self.get_cterm(xst))


def convert_formula(targetmod, osmod, formula):
	"""Convert a parsed formula by raising its propositions to the metalevel"""

	head, *rest = formula

	if head == 'Prop':
		prop = osmod.parseTerm(f'getTerm(metaParse(upModule(\'{targetmod}, false), none, tokenize("{rest[0]}"), \'Prop))')
		prop.reduce()
		return ['Prop', f'prop({prop})']
	elif head == 'Var':
		return formula
	else:
		return [head] + [convert_formula(targetmod, osmod, arg) for arg in rest]


def build_instance(filename, initial_txt, strategy_txt, module_txt=None, semantics_module='NOP-SEMANTICS'):
	"""Build the model for the logic"""

	maude.load(filename)

	# Target module
	targetmod = maude.getCurrentModule() if module_txt is None else maude.getModule(module_txt)

	# Operational semantics module
	maude.input(INSTANTIATION.format(targetmod=targetmod, semanticsmod=semantics_module))
	osmod = maude.getCurrentModule()

	# Create the helper class to handle the instance
	instance = OpSemInstance(osmod, targetmod)

	# Initial term
	initial_term = targetmod.parseTerm(initial_txt)

	if initial_term is None:
		sys.exit(1)

	initial_term.reduce()

	initial_metaterm = osmod.upTerm(initial_term)

	# Strategy expression
	strategy = targetmod.parseStrategy(strategy_txt)

	if strategy is None:
		sys.exit(1)

	strategy_metaterm = osmod.upStrategy(strategy)

	# Construct the terms in the semantics
	t = instance.stack_state(initial_metaterm, strategy_metaterm)

	return instance, t


def srewrite(instance, initial, depth=False):
	index = 1

	# Solutions are found with ->sc instead of ->>, because both
	# produce the same set of solutions and ->sc use less rewrites
	s = instance.osmod.parseStrategy('opsem-sc')

	for sol, nrew in initial.srewrite(s, depth):
		term = instance.get_cterm(sol)
		print(f'\nSolution {index}')
		print(f'rewrites: {nrew}')
		print(f'result {term.getSort()}: {term}')
		index += 1

	print('\nNo solutions.' if index == 1 else '\nNo more solutions.')


def test_benchmark(case_spec):
	for filename, cases in read_suite(case_spec):
		for case, changed in cases:
			if len(case.opaque) > 0:
				continue

			if case.strategy_str is not None and case.ftype == 'LTL':
				print('>>', filename, case.initial, case.strategy, end=' -> ', flush=True)

				instance, t = build_instance(case.filename, case.initial_str, case.strategy_str, case.module_str)

				if args.opaque is None:
					s = instance.osmod.parseStrategy('opsem')
				else:
					opaque_set = ' ; '.join(["'" + name for name in args.opaque.split(',')])
					s = instance.osmod.parseStrategy(f'opsemo({opaque_set})')

				formula = convert_formula(instance.targetmod, instance.osmod, case.formula)

				model = MaudeModel(t, strategy=s, filename='opsem.maude', opaque=['->>'])

				try:
					holds, stats = model.check(formula, logic=case.ftype)

					if holds == case.expected:
						print('OK', stats['states'])
					else:
						print('BAD', stats['states'])

				except KeyboardInterrupt:
					print('CANCELLED')


if __name__ == '__main__':

	import argparse

	##
	## Input data parsing
	##

	parser = argparse.ArgumentParser(description='Small-step operational semantics interface')

	parser.add_argument('file', help='Maude source file or test specification file')
	parser.add_argument('initial', help='Initial term', nargs='?')
	parser.add_argument('strategy', help='Strategy to rewrite that term', nargs='?')
	parser.add_argument('formula', help='Formula to be checked', nargs='?')
	parser.add_argument('--module', '-m', help='Target module')
	parser.add_argument('--opaque', help='Opaque strategies')
	parser.add_argument('--graph', '-g',
	                    help='Produce a graph of the explored system automaton in DOT format when model checking',
	                    action='store_true')
	parser.add_argument('--backend', help='Prioritized list of model-checking backends',
	                    default='maude,ltsmin,pymc,nusmv,builtin')
	parser.add_argument('--verbose', '-v', help='Show more information', action='store_true')
	parser.add_argument('--no-advise', help='Disable advises from Maude', action='store_true')

	args = parser.parse_args()

	if args.initial is not None and args.strategy is None:
		print('An initial term was given, but not a strategy.')
		sys.exit(1)

	maude.init(advise=not args.no_advise)
	maude.load('opsem')

	# Benchmarking
	if args.strategy is None:
		test_benchmark(args.file)
		sys.exit(0)

	# Build the instance of the operational semantics for the given problem
	instance, t = build_instance(args.file, args.initial, args.strategy, args.module)

	# If no formula is given, we only rewrite the term and show the results
	if args.formula is None:
		srewrite(instance, t)
		sys.exit(0)

	# Parse the temporal logic formula
	parser = Parser()
	parser.set_module(instance.targetmod)
	formula, logic = parser.parse(args.formula)

	if args.opaque is None:
		s = instance.osmod.parseStrategy('opsem')
	else:
		opaque_set = ' ; '.join(["'" + name for name in args.opaque.split(',')])
		s = instance.osmod.parseStrategy(f'opsemo({opaque_set})')

	# Convert the formula (atomic propositions are passed to the metalevel)
	formula = convert_formula(instance.targetmod, instance.osmod, formula)

	branching = logic not in ['LTL', 'propLogic']

	# Execute the model checkers
	# (this will not work with LTSmin)
	model = MaudeModel(t, strategy=s, filename='opsem.maude', opaque=['->>'])
	holds, stats = model.check(formula, logic=logic)

	if args.graph:
		with open('opsem.dot', 'w') as dot:
			def print_state_ord(xst):
				part, stack = xst.arguments()
				left, right = instance.targetmod.downTerm(part).arguments()

				if 'right' in [str(arg) for arg in left.arguments()]:
					left, right = right, left

				return '{} |{} @ {}'.format(left, right, instance.print_stack(stack))

			model.print_graph(outfile=dot, sformat=lambda g, n: print_state_ord(g.getStateTerm(n)), eformat='')

	if args.verbose:
		print('Logic:', logic)
		print('Backend:', stats['backend'])

	if holds is not None:
		verb = 'is' if holds else 'is not'
		mark = '\033[1;32m✔\033[0m' if holds else '\033[1;31m✘\033[0m'
		info = model.format_statistics(stats)

		print(f'{mark} The property {verb} satisfied ({info}).')

		if 'counterexample' in stats:
			# Printing the rule applied will be interesting, but that would require modifying the terms
			model.print_counterexample(stats, sformat=lambda g, i: instance.get_cterm(g.getStateTerm(i)), eformat='')
