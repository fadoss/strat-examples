#!/usr/bin/env python3
#
# Interface for model-checking with multistrategies against branching-time properties
#
# It requires the maude (https://pypi.org/project/maude) and umaudemc packages.
# The latter is available at https://github.com/fadoss/umaudemc and also included as
# a file called umaudemc in the strategy-aware model checker downloads. Set PYTHONPATH
# to the full path of this file to run this.
#

import argparse
import sys

import maude

from umaudemc.formulae import Parser
from umaudemc.api import MaudeModel

##
## Input data parsing
##

parser = argparse.ArgumentParser(description='Multistrategies model-checking interface')

parser.add_argument('file', help='Maude source file')
parser.add_argument('initial', help='Initial term')
parser.add_argument('formula', help='Formula to be checked (or a dash to execute the multistrategy)')
parser.add_argument('gamma', help='Strategy that control how multistrategies are executed (turns, concurrent or strategy expression)')
parser.add_argument('strategy', help='Multistrategies', nargs='+')
parser.add_argument('--module', '-m', help='Target module')
parser.add_argument('--backend', help='Prioritized list of model-checking backends', default='maude,ltsmin,pymc,nusmv,builtin')
parser.add_argument('--verbose', '-v', help='Show more information', action='store_true')

args = parser.parse_args()

##
## Counterexample printing
##

def print_term(graph, index):
	state = graph.getStateTerm(index)
	term = target_module.downTerm(next(state.arguments()))
	return str(term)

def print_log(log_term):
	player, strat = list(log_term.arguments())

	return f'{player} does {target_module.downStrategy(strat)}'

def print_logs(graph, origin, dest):
	state = graph.getStateTerm(dest)
	threads = list(state.arguments())[1]

	if str(threads.symbol()) != '__':
		return ''

	logs = [print_log(arg) for arg in threads.arguments() if str(arg.symbol()) == 'log']

	return ', '.join(logs)

##
## Model checking
##

# Load Maude
maude.init(advise=False)

# Construct the module where to model check membrane systems
maude.load(args.file)

if args.module is None:
	args.module = str(maude.getCurrentModule())

maude.load('multistrat')

ms_external = maude.getModule('MULTISTRAT-EXTERNAL')

if ms_external is None:
	print('Error: cannot find multistrategy infraestructure (multistrat.maude).')
	sys.exit(1)

term_kind     = ms_external.findSort('Term').kind()
module_kind   = ms_external.findSort('Module').kind()
strategy_kind = ms_external.findSort('StrategyList').kind()
ms_context    = ms_external.findSort('MSContext').kind()
ms_threadset  = ms_external.findSort('MSThreadSet').kind()
result_pair   = ms_external.findSort('ResultPair')
strategy_sort = ms_external.findSort('Strategy')
ms_formula    = ms_external.findSort('Formula').kind()

if None in [term_kind, module_kind, strategy_kind, ms_context, result_pair, strategy_sort, ms_formula]:
	print('Error: bad multistrat.maude (missing sorts).')
	sys.exit(1)

make_context  = ms_external.findSymbol('makeContext', [term_kind, strategy_kind, module_kind], ms_context)
strategy_list = ms_external.findSymbol('_`,_', [strategy_kind] * 2, strategy_kind)
meta_prop     = ms_external.findSymbol('prop', [term_kind], ms_formula)
# makeContext

if None in [make_context, strategy_list, meta_prop]:
	print('Error: bad multistrat.maude (missing operators).')
	sys.exit(1)

# Parse the initial term
initial = ms_external.parseTerm(f'metaParse(upModule(\'{args.module}, false), none, tokenize("{args.initial}"), anyType)')
initial.reduce()

if not initial.getSort().leq(result_pair):
	print('Error: cannot parse initial term.')
	sys.exit(1)

initial = next(initial.arguments())

# Parse the strategy expressions
multistrats = []

for strat in args.strategy:
	strat_term = ms_external.parseTerm(f'metaParseStrategy(upModule(\'{args.module}, false), none, tokenize("{strat}"))')
	strat_term.reduce()

	if not strat_term.getSort().leq(strategy_sort):
		print(f'Error: cannot parse strategy {strat}.')
		sys.exit(2)

	multistrats.append(strat_term)

# Parse the controlling strategy expression
gamma_text = args.gamma

if gamma_text == 'turns':
	gamma_text = f'turns(0, {len(multistrats)})'
elif gamma_text == 'concurrent':
	gamma_text = 'freec'

gamma = ms_external.parseStrategy(gamma_text)

if gamma is None:
	print(f'Error: cannot parse gamma strategy.')

# Make the context
context = make_context(
	initial,
	strategy_list.makeTerm(multistrats) if len(multistrats) > 0 else multistrats[0],
	ms_external.parseTerm(f'upModule(\'{args.module}, true)')
)

# Obtain the target (object-level) module
target_module = maude.getModule(args.module)

# If the formula is a dash, we simply execute the strategy
if args.formula == '-':
	index = 1

	for sol, nrew in context.srewrite(gamma):
		term = target_module.downTerm(next(sol.arguments()))
		print(f'\nSolution {index}')
		print(f'rewrites: {nrew}')
		print(f'result {term.getSort()}: {term}')
		index += 1

	print('\nNo solutions.' if index == 1 else '\nNo more solutions.')
	sys.exit(0)

# Parse the temporal logic formula
parser = Parser()
parser.set_module(target_module)
formula, logic = parser.parse(args.formula)

def convert_formula(formula):
	head, *rest = formula

	if head == 'Prop':
		prop = ms_external.parseTerm(f'getTerm(metaParse(upModule(\'{args.module}, false), none, tokenize("{rest[0]}"), \'Prop))')
		prop.reduce()
		return ['Prop', f'prop({prop})']
	elif head == 'Var':
		return formula
	else:
		return [head] + [convert_formula(arg) for arg in rest]

# Convert the formula (atomic propositions are passed to the metalevel)
formula = convert_formula(formula)

branching = logic not in ['LTL', 'propLogic']

# Execute the model checkers
model = MaudeModel(context, strategy=gamma, filename='multistrat.maude')
holds, stats = model.check(formula, logic=logic, backends=args.backend, merge_states='edge' if branching else 'no')

if args.verbose:
	print('Logic:', logic)
	print('Backend:', stats['backend'])

if holds is not None:
	verb = 'is' if holds else 'is not'
	mark = '\033[1;32m✔\033[0m' if holds else '\033[1;31m✘\033[0m'
	info = model.format_statistics(stats)

	print(f'{mark} The property {verb} satisfied ({info}).')

	if 'counterexample' in stats:
		model.print_counterexample(stats, sformat=print_term, eformat=print_logs)
