Examples of the Maude strategy language
=======================================

This repository contains several strategy-controlled specifications and programs written using the [strategy language](http://maude.ucm.es/strategies) of the [Maude](http://maude.cs.illinois.edu) rewriting-logic framework. An index is available [here](https://fadoss.github.io/strat-examples).

The initial comments of some files indicate their authors and the publication where they were first presented. These examples have usually been updated to be used in the latest version of the strategy language, and sometimes they have been corrected and improved. External specifications are also included in this repository as submodules, which can be checked out with `git submodule update --init`.

Most examples can be run with the latest official version of Maude, but the model-checking ones require an extended version available [here](http://maude.ucm.es/strategies/#downloads). Moreover, for those including branching-time and probabilistic properties, the [`umaudemc`](https://github.com/fadoss/umaudemc) tool should be used.


Testing
-------

In the `tests` directory, some tests are available for most of the examples along with their expected outputs, which can be checked with the `test.sh` script. The `modelChecking.yaml` file contains many model-checking test cases that should be run with the `test` subcommand of the [`umaudemc`](https://github.com/fadoss/umaudemc) tool.
