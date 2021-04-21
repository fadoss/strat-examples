#!/usr/bin/env python3
#
# Interface for model-checking membrane systems against branching-time properties
#
# It requires the maude (https://pypi.org/project/maude/) and umaudemc packages.
# The latter is included as a file called umaudemc in the strategy-aware model
# checker downloads. Set PYTHONPATH to the full path of that file to run this.
#

import argparse
import sys

import maude
from umaudemc.api import MaudeModel

##
## Input data parsing
##

parser = argparse.ArgumentParser(description='Membrane systems model-checking interface')

parser.add_argument('file', help='Membrane specification file')
parser.add_argument('membrane', help='Initial membrane')
parser.add_argument('formula', help='Formula to be checked')
parser.add_argument('--priority', help='Priority interpretation', choices=['weak', 'strong'], default='strong')
parser.add_argument('--depth', help='Model bound on the number of steps', type=int, default=0)
parser.add_argument('--objbound', help='Model bound on the number of objects', type=int, default=0)
parser.add_argument('--backend', help='Prioritized list of model-checking backends', default='maude,ltsmin,pymc,nusmv,builtin')
parser.add_argument('--verbose', '-v', help='Show more information', action='store_true')

if '--' in sys.argv:
	index = sys.argv.index('--')
	own_args, extra_args = sys.argv[1:index], sys.argv[index+1:]
else:
	own_args, extra_args = sys.argv[1:], []

args = parser.parse_args(args=own_args)

##
## Counterexample printing
##
## The following functions print the membrane multiset without logs
## and the logs separately, to be states and edges of counterexamples.
##

def print_membrane(graph, index):
	state = graph.getStateTerm(index)

	if str(state.symbol()) == '__':
		printable = [str(arg) for arg in state.arguments() if str(arg.symbol()) != 'log']
	else:
		printable = [str(state)]

	return ' '.join(printable)

def print_log(log_term):
	name, rls = list(log_term.arguments())

	if str(rls.symbol()) == '_;_':
		rls_str = [str(arg)[1:] for arg in rls.arguments()]
	else:
		rls_str = [str(rls)[1:]]

	return f'{" ".join(rls_str)} for {name}'

def print_logs(graph, origin, dest):
	state = graph.getStateTerm(dest)

	if str(state.symbol()) != '__':
		return ''

	logs = [print_log(arg) for arg in state.arguments() if str(arg.symbol()) == 'log']

	return ', '.join(logs)


##
## Model checking
##

# Load Maude
maude.init(advise=False)

# Try to open the membrane specification file and prepare it
try:
	with open(args.file, 'r') as membf:
		membs = membf.read()

except FileNotFoundError as fnfe:
	print(fnfe)
	sys.exit(1)

# Escape line breaks and other to make this a Maude string
membs = membs.replace('\n', '\\n').replace('"', '\\"').replace('\t', ' ')

# Construct the module where to model check membrane systems
maude.load('memparse')

membrane_external = maude.getModule('MEMBRANE-EXTERNAL')
module_term = membrane_external.parseTerm(f'makeMMCModule("{membs}", {"false" if args.priority == "weak" else "true"}, {args.objbound})')
nrewrites = module_term.reduce()

if args.verbose:
	print(f'Rewriting model generated from membrane specification ({nrewrites} rewrites)')

# The rewrite theory for the membrane system as a Module object
mmc_module = maude.downModule(module_term)

if mmc_module is None:
	print('Error when computing the Maude module for the membrane system.')
	sys.exit(1)

# Parse the initial membrane
t = mmc_module.parseTerm(args.membrane)
s = mmc_module.parseStrategy('%mcomp%')

if t is None:
	print('Bad parse for initial membrane.')
	sys.exit(1)

# Execute the model checkers
model = MaudeModel(t, strategy=s, filename='memparse.maude',
	           metamodule=module_term,
	           opaque=['%step%'])

holds, stats = model.check(args.formula,
			   backends=args.backend,
			   depth=args.depth,
			   purge_fails=False,
			   merge_states='no',
			   extra_args=extra_args)

if holds is None:
	# Error messages should have already been printed
	sys.exit(1)

if args.verbose:
	print('Logic:', stats['logic'])
	print('Backend:', stats['backend'])

if holds is not None:
	verb = 'is' if holds else 'is not'
	mark = '\033[1;32m✔\033[0m' if holds else '\033[1;31m✘\033[0m'
	info = model.format_statistics(stats)

	print(f'{mark} The property {verb} satisfied ({info}).')

	if 'counterexample' in stats:
		model.print_counterexample(stats, sformat=print_membrane, eformat=print_logs)
