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
provided in `models/`.

This repository also provides access to several trained models. Config files for these are given in
the `models/` directory, and the models themselves can be interactively downloaded with
`scripts/setup/download.py`. The ones included here were identified by hyperparameter tuning across
the various settings covered by the config generator. Only a few are provided because I lost track
of the best models for a lot of configurations, since the training was done quite a while ago. If
you make any changes or train more models, please send them along!

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

### Training

Training is done in the normal AllenNLP style. Given that you have a `config.json` specifying your
model, you can run
```bash
python -m allennlp.run train config.json --include-package qasrl -s save
```
from the base directory of this repository, and it will initiate a training run with results in
`save/`.

### Running a model

Most of our QA-SRL models are constructed as pipelines. So to run predictions, instead of using
AllenNLP Predictors, I have separate pipeline scripts which take the pipeline constituents as
parameters. These are in [`qasrl/pipelines/`](qasrl/pipelines), and should just be invoked with
`python` from the command line. See each pipeline script for details on arguments, etc., but for
example, to run a span detection -> question generation pipeline, I might invoke
```bash
python qasrl/pipelines/afirst_pipeline_sequential.py \
  --span models/span_density_softmax.tar.gz \
  --span_to_question models/span_to_question.tar.gz \
  --cuda_device 0 \
  --span_min_prob 0.02 \
  --question_min_prob 0.01 \
  --question_beam_size 20 \
  --input_file data/qasrl-dev-mini.jsonl \
  --output_file out.jsonl
```
which will write complete model predictions at `out.jsonl`.

#### Input file format

The format of the input file should be jsonl, where each sentence has a dictionary
 representing it. The must-have keys are "sentenceId", "sentenceTokens", "verbEntries".

So for the sentence "Both occur suddenly.", The representive json should look as
  follows:

```json
{"sentenceId":"1",
"sentenceTokens":["Both","occur","suddenly","."],
"verbEntries":{"1":{"verbIndex":1,"verbInflectedForms":{"stem":"occur","presentSingular3rd":"occurs","presentParticiple":"occurring","past":"occurred","pastParticiple":"occurred"}}}}
```

1. "sentenceId": Is copied as is to the output file.
2. "sentenceTokens": Its value is a list of the sentence's tokens.
3. "verbEntries": Its value is a dictionary, where each key is a string representing
 the index of a verb token in the sentence, and the inner dict should include verbIndex
  (as an integer), and verbInflectedForms.

There is a conversion script that outputs this format of a file under 
[`qasrl/scripts/utils/prepare_input_file.py`](qasrl/scripts/utils/prepare_input_file.py). 

### Hyperparameter tuning

To do hyperparameter tuning, first you generate the config files for all hyperparameter settings.
To do this, make sure Mill is installed and run
```bash
mill -i utils.model-gen.run configs
```
which will create a `configs/` directory and place all of the autogenerated configs there. You can
change the set of configs that is generated by editing
[`ModelVariants.scala`](utils/model-gen/src-jvm/ModelVariants.scala).

Once the config files are all generated, you will want to do training runs of all of them and sift
through the results. Utilities and scripts to do this are in this repository, but they're specific
to Slurm and the Hyak compute infrastructure so they may not be the easiest way of doing it for you.
Also, I don't remember exactly how it all worked. So I imagine youll roll your own method (but I can
help with more documentation on the slurm stuff if someone needs it).


