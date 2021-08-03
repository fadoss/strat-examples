#!/usr/bin/env python3
#
# Draw CRN trajectories
#
# Requires a version of the Maude library including the probabilistic
# extension of the Maude strategy language
#

import maude
import numpy as np
import matplotlib.pyplot as plt


def simulate(initial, N):
	t = initial

	time = np.zeros(N)
	pos  = np.zeros((N, 2))

	for k in range(N):
		x, y, tm = t.arguments()
		x, y, tm = int(x), int(y), float(tm)

		time[k] = tm
		pos[k] = [x, y]

		(t, _),*_ = t.srewrite(step)

	return time, pos


if __name__ == '__main__':
	import argparse

	parser = argparse.ArgumentParser(description='CRN trajectory plotter')

	parser.add_argument('--file', '-f', help='Maude specification file', default='pred-prey.maude')
	parser.add_argument('--initial', help='Initial term', default='initial')
	parser.add_argument('--strategy', help='Strategy for a reaction step', default='step')
	parser.add_argument('-n', help='Number of steps', type=float, default=1e3)
	parser.add_argument('--save', help='Save data to file', type=str)
	parser.add_argument('--load', help='Load data from file', type=str)

	args = parser.parse_args()

	# Load previously saved simulation data
	if args.load:
		with np.load(args.load + '.npz') as loaded:
			rtime, pos = loaded['rtime'], loaded['pos']

	# Load Maude and the CRN model to simulate it
	else:
		maude.init()
		maude.load(args.file)

		m = maude.getCurrentModule()
		initial = m.parseTerm(args.initial)
		step = m.parseStrategy(args.strategy)

		initial.reduce()

		# Simulate the model for args.n steps
		rtime, pos = simulate(initial, int(args.n))
		print('Total reaction time', rtime[-1])

		# Save the simulation data
		if args.save:
			np.savez(args.save + '.npz', rtime=rtime, pos=pos)

	# Plot the trajectory (for two species)
	plt.plot(pos[:, 0], pos[:, 1])
	plt.xlabel('Prey')
	plt.ylabel('Predator')
	plt.savefig('crn-trajectory.png')
	plt.show()

	# Plot the number of species with respect to time
	plt.plot(rtime, pos)
	plt.legend(('Prey', 'Predator'))
	plt.xlabel('Time')
	plt.ylabel('Number of species')
	plt.savefig('crn-wrtime.png')
	plt.show()
