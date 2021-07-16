# qasrl-modeling
Neural network models for QA-SRL.

## Contents

This repository contains code for training and running QA-SRL models in a variety of pipeline
formats: from span detection to question generation
(as in [FitzGerald et al., 2018](https://aclanthology.org/P18-1191.pdf))
as well as the reverse order (question generation to question answering),
and accommodating a wide range of question formats (for example, prototype QA-SRL questions which
have tense, aspect, animacy, etc. normalized out).
There is also clause-based question modeling which was part of a project that hasn't been published
(and probably won't be), and which might not run properly right now.

In addition to the Python (PyTorch/AllenNLP) code for the models, there is also a set of Scala
utilities for generating config files, processing QA-SRL questions, and evaluating models. The
evaluations aren't the standard published ones and haven't made it into any papers, so you should
probably instead go with the methodology suggested by
[Roit et al. (2020)](https://www.aclweb.org/anthology/2020.acl-main.626/).
You'll probably only need to run the Scala code if you want to generate new config files to do
hyperparameter optimization or for a model format that isn't covered by one of the config files
provided in `???/`.

## Setup

At the moment, this repository needs Python version 3.8. Be aware that this is not the newest
Python. I would recommend getting set up as follows:
```bash
> python3.8 -m venv env
> source env/bin/activate
> pip install --upgrade pip
> pip install -r requirements.txt
```
This will create a local virtual environment with the right Python and AllenNLP versions (plus some
other pinned dependencies). It'd be great to update to the latest versions of everything,
but I would have to test it all to make sure it works. So I haven't done that for now.

To run the Scala code, you need to first install
[Mill](https://com-lihaoyi.github.io/mill/mill/Intro_to_Mill.html).

## Usage
