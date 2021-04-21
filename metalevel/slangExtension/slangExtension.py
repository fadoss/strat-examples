#!/usr/bin/env python3
#
# Interface for model checking with extensions of the strategy language
#
# It requires the maude (https://pypi.org/project/maude/) and umaudemc packages.
# The latter is included as a file called umaudemc in the strategy-aware model
# checker downloads. Set PYTHONPATH to the full path of that file to run this.
#

#
# For example, the congruence operators extension can be executed with
#
#	./slangExtension.py congruenceOpsExt.maude CongOps congruence-foo.maude \
#		'f(f(a, b), f(a, a))' 'f(swap , gt-all(next))'
#
# Some models may not work due to conflicts between extended strategy operators
# and standard ones.
#

import argparse
import os.path
import sys
import uuid

import maude
from umaudemc.api import MaudeModel


def show_error(text):
	print('\033[1;31mError: \033[0m' + text, file=sys.stderr)


class SlangExtension:
	"""Extension of the Maude strategy language"""

	def __init__(self, view):
		self.view = view
		self.extension = None
		self.module_kind = None
		self.parseModule = None
		self.makeSlangGrammar = None
		self.makeMetaSlang = None
		self.stratModule_sort = None
		self.parseModule = None
		self.flatModule = None

	def load(self):
		"""Load and check the extension"""

		# The module defining the extension and the required functions
		self.extension = maude.getModule(self.view)

		makeSlangGrammar_name = 'makeSlangGrammar'
		makeMetaSlang_name    = 'makeMetaSlang'

		if self.extension is None:
			view = maude.getView(self.view)

			if view is None:
				show_error('Not a module or view: ' + args.view)
				return False

			# Instantiating a view is not simple because the library does not offer many
			# tools for this, and because views may have been defined using op-to-term
			# mappings and the expected symbols may not be present in the module

			# Except the last two modules, this can be done once for all

			modid = uuid.uuid1()

			makeSlangGrammar_name = f'{modid}-makeSlangGrammar'
			makeMetaSlang_name    = f'{modid}-makeMetaSlang'

			# Create a strategy module where the functions makeSlangGrammar
			# and makeMetaSlang are properly defined
			maude.input(f'''smod MOD-{modid}{{X :: SLANG-EXTENSION}} is
				op {modid}-makeSlangGrammar : Module -> Module .
				op {modid}-makeMetaSlang : Module -> Module .
				var M : Module .
				eq {modid}-makeSlangGrammar(M) = makeSlangGrammar(M) .
				eq {modid}-makeMetaSlang(M) = makeMetaSlang(M) .
			endsm''')

			# Instantiate the view
			maude.input(f'''smod INST-{modid} is
				protecting MOD-{modid}{{{self.view}}} .
				protecting SMOD-PARSE{{{self.view}}} .
			endsm''')

			self.extension = maude.getModule(f'INST-{modid}')

		module_kind = self.extension.findSort('Module').kind()

		self.makeSlangGrammar = self.extension.findSymbol(makeSlangGrammar_name, [module_kind], module_kind)
		self.makeMetaSlang    = self.extension.findSymbol(makeMetaSlang_name, [module_kind], module_kind)

		if self.makeSlangGrammar is None or self.makeMetaSlang is None:
			show_error('Cannot find the expected operators in the extension module.')
			return False

		# Find the parseModule symbol (but do not fail if not found)
		string_kind           = self.extension.findSort('String').kind()
		self.stratModule_sort = self.extension.findSort('StratModule')

		self.parseModule = self.extension.findSymbol('parseModule', [string_kind], module_kind)
		self.flatModule = self.extension.findSymbol('flatModule', [module_kind], module_kind)

		return True

	def read_module(self, module_text):
		"""Parse an extended module (given as a string)"""

		if self.parseModule is None or self.flatModule is None:
			show_error('The extension does not support module parsing (include the SMOD-PARSE module).')
			return None, None

		module_text = module_text.replace('"', '\\"').replace('\n', '\\n').replace('\t', '\\t')

		parsed_module = self.flatModule(self.parseModule(self.extension.parseTerm(f'"{module_text}"')))
		parsed_module.reduce()

		if not parsed_module.getSort() <= self.stratModule_sort:
			show_error('The given extended module cannot be parsed.')
			return None, None

		return self._instantiate(parsed_module), parsed_module

	def instantiate(self, metamodule):
		"""Instantiate the extension on a given module (as a metamodule string)"""

		metamod_term = self.extension.parseTerm(metamodule)
		return self._instantiate(metamod_term)

	def _instantiate(self, metamod_term):
		"""Instantiate the extension on a given metamodule"""

		# Build the extended strategy language grammar module
		grammar_modterm = self.makeSlangGrammar(metamod_term)
		grammar_mod     = maude.downModule(grammar_modterm)

		if grammar_mod is None:
			show_error('Cannot use grammar module' + (f': {str(grammar_modterm)}' if args.verbose else '.'))
			return None

		# Build the extended metalevel module for the extended language
		metaslang_modterm = self.makeMetaSlang(metamod_term)
		metaslang_mod     = maude.downModule(metaslang_modterm)

		if metaslang_mod is None:
			show_error('Cannot use extended metalevel' + (f': {str(metaslang_modterm)}' if args.verbose else '.'))
			return None

		# Get the stratParse and transform operators to parse and convert
		# the strategies to the standard language
		module_kind     = metaslang_mod.findSort('Module').kind()
		term_kind       = metaslang_mod.findSort('Term').kind()
		strat_kind      = metaslang_mod.findSort('Strategy').kind()
		nat_kind        = metaslang_mod.findSort('Nat').kind()

		stratParse    = metaslang_mod.findSymbol('stratParse', [module_kind, term_kind], strat_kind)
		transform     = metaslang_mod.findSymbol('transform', [strat_kind, nat_kind], strat_kind)
		zero          = metaslang_mod.parseTerm('0', nat_kind)
		strategy_kind = grammar_mod.findSort('@Strategy@').kind()

		if any(symb is None for symb in [stratParse, transform, zero, strategy_kind]):
			show_error('Missing requirements in the strategy extension module.')
			return None

		# The metarepresentation of the grammar module is in the extension term,
		# but the instance need it as a term of the extended metalevel
		grammar_modterm_in_metaslang = metaslang_mod.parseTerm(str(grammar_modterm))

		return SlangExtInstance(grammar_mod, grammar_modterm_in_metaslang,
					metaslang_mod, stratParse, transform,
					strategy_kind, zero)


class SlangExtInstance:
	"""Instance of a strategy language extension"""

	def __init__(self, grammar_mod, grammar_modterm, metaslang_mod, stratParse, transform, strategy_kind, zero):
		self.grammar = grammar_mod
		self.grammar_modterm = grammar_modterm
		self.metaslang = metaslang_mod
		self.strategy_kind = self.grammar.findSort('@Strategy@').kind()
		self.stratParse = stratParse
		self.transform = transform
		self.strategy_kind = strategy_kind
		self.zero = zero

	def parse_strategy(self, text):
		"""Parse a strategy and return its metarepresentation in the standard language"""

		# Parse the given input strategy
		strategy = self.grammar.parseTerm(text, self.strategy_kind)

		if strategy is None:
			show_error('Cannot parse extended strategy: ' + args.strategy)
			return None

		upstrategy = self.metaslang.upTerm(strategy)

		metastrategy = self.transform(self.stratParse(self.grammar_modterm, upstrategy), self.zero)
		metastrategy.reduce()

		return metastrategy

if __name__ == '__main__':

	##
	## Input data parsing
	##

	parser = argparse.ArgumentParser(description='Model-checking interface for strategy language extensions')

	parser.add_argument('extension', help='Maude file specifying the strategy language extension')
	parser.add_argument('view', help='Module or view describing the strategy language extension')
	parser.add_argument('file', help='Maude specification file')
	parser.add_argument('initial', help='Initial term')
	parser.add_argument('strategy', help='Formula to be checked')
	parser.add_argument('formula', help='Formula to be checked', nargs='?')
	parser.add_argument('--extmodule',
			    help='Extended strategy module (whose strategy definitions use the extended strategy language) where to model check')
	parser.add_argument('--module', help='Module where to model check')
	parser.add_argument('--metamodule', help='Term that reduces to a metamodule where to model check')
	parser.add_argument('--depth', help='Model bound on the number of steps', type=int, default=0)
	parser.add_argument('--opaque', help='Comma-separated list of opaque strategies', default='')
	parser.add_argument('--backend', help='Prioritized list of model-checking backends', default='maude,ltsmin,pymc,nusmv,builtin')
	parser.add_argument('--verbose', '-v', help='Show more information', action='store_true')

	if '--' in sys.argv:
		index = sys.argv.index('--')
		own_args, extra_args = sys.argv[1:index], sys.argv[index+1:]
	else:
		own_args, extra_args = sys.argv[1:], []

	args = parser.parse_args(args=own_args)

	##
	## Model checking
	##

	# Load the Maude specifications of the extension and the model
	maude.init(advise=False)

	if not os.path.isfile(args.extension):
		show_error('Cannot find strategy language extension file: ' + args.extension)
		sys.exit(1)

	if not os.path.isfile(args.file):
		show_error('Cannot find Maude file: ' + args.file)
		sys.exit(1)

	maude.load(args.extension)
	maude.load(args.file)

	# The module where the extended strategies will be used...
	base_module = maude.getCurrentModule() if args.module is None else maude.getModule(args.module)

	# ...unless a metamodule is specified
	if args.metamodule is not None:
		metamodule = args.metamodule

		metamod_term = base_module.parseTerm(metamodule)
		module = maude.downModule(metamod_term)
		metamodule = str(metamod_term)

	elif args.extmodule is None:
		metamodule = f"upModule('{str(base_module)}, true)"
		module = base_module

	# Load the strategy language extension
	extension = SlangExtension(args.view)

	if not extension.load():
		sys.exit(1)

	# The subject module can be a standard module or a extended one
	if args.extmodule is None:
		instance = extension.instantiate(metamodule)

		if instance is None:
			sys.exit(1)

		parsed_module = None

	else:
		extmodule = args.extmodule

		# Extended modules can be read from file
		if not extmodule.startswith('smod') and os.path.isfile(extmodule):
			with open(extmodule, 'r') as modf:
				extmodule = modf.read()
		
		# Remove comments from the file
		extmodule = '\n'.join([line for line in extmodule.splitlines() if not line.startswith('***')])

		instance, parsed_module = extension.read_module(extmodule)

		if instance is None:
			sys.exit(1)

		module = maude.downModule(parsed_module)

		if module is None:
			show_error('The extended module cannot be used.')
			sys.exit(1)

	# Parse the extended strategy
	metastrategy = instance.parse_strategy(args.strategy)

	if metastrategy is None:
		sys.exit(1)

	# Parse the initial term
	t = module.parseTerm(args.initial)
	s = module.downStrategy(metastrategy)

	if args.verbose:
		print('Transformed strategy:', s)

	# If no formula was given, the strategy is simply executed
	if args.formula is None:
		index = 1
	
		for sol, nrew in t.srewrite(s):
			print(f'\nSolution {index}')
			print(f'rewrites: {nrew}')
			print(f'result {sol.getSort()}: {sol}')
			index += 1

		print('\nNo solutions.' if index == 1 else '\nNo more solutions.')
		sys.exit(0)

	# Check whether the module is prepared for model checking
	if module.findSort('Formula') is None or module.findSort('ModelCheckResult') is None:
		show_error(f'The module {str(module)} is not prepared for model checking.')
		sys.exit(1)

	# Execute the model checkers
	model = MaudeModel(t,
			   strategy=s,
			   filename=args.file,
			   metamodule=parsed_module,
			   module=None if parsed_module is None else 'META-LEVEL',
			   opaque=args.opaque)

	holds, stats = model.check(args.formula,
				   backends=args.backend,
				   extra_args=extra_args)

	if args.verbose:
		print('Logic:', stats['logic'])
		print('Backend:', stats['backend'])

	if holds is not None:
		verb = 'is' if holds else 'is not'
		mark = '\033[1;32m✔\033[0m' if holds else '\033[1;31m✘\033[0m'
		info = model.format_statistics(stats)

		print(f'{mark} The property {verb} satisfied ({info}).')

		if 'counterexample' in stats:
			model.print_counterexample(stats)
