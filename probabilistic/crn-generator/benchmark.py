#!/usr/bin/env python3
#
# Benchmark tool for the abstraction generators produced by maudify.py
#

import csv
import os
import subprocess
import sys
import tempfile
import time

# Compiler for the C version
COMPILER = ('gcc', '-O3', '-mtune=native')
CXXCOMPILER = ('g++', '-O3', '-mtune=native')


def run_c(mfile, compiler=COMPILER, cpp=False):
	"""Run the simulation using C/C++"""

	suffix = '.cc' if cpp else '.c'

	with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
		with open(f'results/{os.path.basename(mfile)}{suffix}.txt', 'w') as ofile:
			biname = tmp.name + '.out'

			start_time = time.time_ns()
			subprocess.run([sys.executable, 'maudify.py', '-c++' if cpp else '-c', mfile], stdout=tmp)
			tmp.flush()
			subprocess.run(list(compiler) + [tmp.name, '-o', biname])
			subprocess.run([biname], stdout=ofile)
			end_time = time.time_ns()

	return end_time - start_time


def run_cpp(mfile, compiler=CXXCOMPILER):
	"""Run the simulation using C++"""

	return run_c(mfile, compiler, cpp=True)


def run_maude(mfile):
	"""Run the simulation using Maude"""

	with open(f'results/{os.path.basename(mfile)}.maude.txt', 'w') as ofile:
		start_time = time.time_ns()
		subprocess.run([sys.executable, 'runMaude.py', mfile, '-'], stdout=ofile)
		end_time = time.time_ns()

	return end_time - start_time


if __name__ == '__main__':

	# Make a directory to store the results
	os.makedirs('results', exist_ok=True)

	alternatives = (
		('cc', run_c),
		('cpp', run_cpp),
		('maude', run_maude),
	)

	with open('results/executions.csv', 'w') as csvfile:
		log = csv.writer(csvfile)
		log.writerow(['model', 'generator', 'time_ns'])

		for mfile in sys.argv[1:]:
			print('**', mfile)

			for name, func in alternatives:
				print('  with', name)

				etime = func(mfile)
				log.writerow([mfile, name, etime])
				csvfile.flush()

