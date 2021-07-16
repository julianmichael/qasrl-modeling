 # completely ridiculous hack to import stuff properly. somebody save me from myself
import importlib
from allennlp.common.util import import_submodules
importlib.invalidate_caches()
import sys
sys.path.append(".")
import_submodules("qasrl")

from typing import List, Iterator, Optional

import torch, os, json, tarfile, argparse, uuid, shutil
import sys

from overrides import overrides

from allennlp.common.util import lazy_groups_of
from allennlp.common.checks import check_for_gpu, ConfigurationError
from allennlp.common.util import JsonDict, sanitize
from allennlp.common.util import get_spacy_model
from allennlp.data import Instance
from allennlp.data.dataset import Batch
from allennlp.data.fields import ListField, SpanField, LabelField
from allennlp.nn.util import move_to_device
from allennlp.data import DatasetReader, Instance
from allennlp.models import Model
from allennlp.models.archival import load_archive, Archive
from allennlp.predictors.predictor import JsonDict, Predictor

from allennlp.common.file_utils import cached_path
from qasrl.data.util import read_lines, get_verb_fields, get_slot_label_namespace

from qasrl.data.dataset_readers import QasrlReader
from qasrl.models.question import QuestionModel
from qasrl.models.question_to_span import QuestionToSpanModel
from qasrl.models.multiclass import MulticlassModel
from qasrl.models.span_to_tan import SpanToTanModel
from qasrl.models.animacy import AnimacyModel
from qasrl.util.archival_utils import load_archive_from_folder

span_minimum_threshold_default = 0.10
question_minimum_threshold_default = 0.03
tan_minimum_threshold_default = 0.20
question_beam_size_default = 10

class QFirstPipeline():
    def __init__(self,
                 question_model_archive: Archive,
                 # question_model_dataset_reader: QasrlReader,
                 question_to_span_model_archive: QuestionToSpanModel,
                 # question_to_span_model_dataset_reader: QasrlReader,
                 tan_model_archive: Optional[Archive] = None,
                 span_to_tan_model_archive: Optional[Archive] = None,
                 animacy_model_archive: Optional[Archive] = None,
                 question_minimum_threshold: float = question_minimum_threshold_default,
                 span_minimum_threshold: float = span_minimum_threshold_default,
                 tan_minimum_threshold: float = tan_minimum_threshold_default,
                 question_beam_size: int = question_beam_size_default,
                 clause_mode: bool = False) -> None:
        self._question_model = question_model_archive.model
        self._question_model_dataset_reader = DatasetReader.from_params(question_model_archive.config["dataset_reader"].duplicate())
        print("Question model loaded.", flush = True)
        self._question_to_span_model = question_to_span_model_archive.model
        self._question_to_span_model_dataset_reader = DatasetReader.from_params(question_to_span_model_archive.config["dataset_reader"].duplicate())
        print("Question-to-span model loaded.", flush = True)
        if tan_model_archive is not None:
            self._tan_model = tan_model_archive.model
            self._tan_model_dataset_reader = DatasetReader.from_params(tan_model_archive.config["dataset_reader"].duplicate())
            print("TAN model loaded.", flush = True)
        else:
            self._tan_model = None
        if span_to_tan_model_archive is not None:
            self._span_to_tan_model = span_to_tan_model_archive.model
            self._span_to_tan_model_dataset_reader = DatasetReader.from_params(span_to_tan_model_archive.config["dataset_reader"].duplicate())
            print("Span-to-TAN model loaded.", flush = True)
        else:
            self._span_to_tan_model = None
        if animacy_model_archive is not None:
            self._animacy_model = animacy_model_archive.model
            self._animacy_model_dataset_reader = DatasetReader.from_params(animacy_model_archive.config["dataset_reader"].duplicate())
            print("Animacy model loaded.", flush = True)
        else:
            self._animacy_model = None
        print("All models loaded.", flush = True)

        self._span_minimum_threshold = span_minimum_threshold
        self._question_minimum_threshold = question_minimum_threshold
        self._tan_minimum_threshold = tan_minimum_threshold
        self._question_beam_size = question_beam_size
        self._clause_mode = clause_mode

        qg_slots = set(self._question_model.get_slot_names())
        qa_slots = set(self._question_to_span_model.get_slot_names())
        if not qa_slots.issubset(qg_slots):
            raise ConfigurationError(
                "Question Answerer must read in a subset of question slots generated by the Question Generator. " + \
                ("QG slots: %s; QA slots: %s" % (qg_slots, qa_slots)))

    def predict(self, inputs: JsonDict) -> JsonDict:
        qg_instances = list(self._question_model_dataset_reader.sentence_json_to_instances(inputs, verbs_only = True))
        qa_instances = list(self._question_to_span_model_dataset_reader.sentence_json_to_instances(inputs, verbs_only = True))
        if self._tan_model is not None:
            tan_instances = list(self._tan_model_dataset_reader.sentence_json_to_instances(inputs, verbs_only = True))
            tan_outputs = self._tan_model.forward_on_instances(tan_instances)
        else:
            tan_outputs = [None for _ in qg_instances]
        if self._span_to_tan_model is not None:
            span_to_tan_instances = list(self._span_to_tan_model_dataset_reader.sentence_json_to_instances(inputs, verbs_only = True))
        else:
            span_to_tan_instances = [None for _ in qg_instances]
        if self._animacy_model is not None:
            animacy_instances = list(self._animacy_model_dataset_reader.sentence_json_to_instances(inputs, verbs_only = True))
        else:
            animacy_instances = [None for _ in qg_instances]

        verb_dicts = []
        for (qg_instance, qa_instance_template, tan_output, span_to_tan_instance, animacy_instance) in zip(qg_instances, qa_instances, tan_outputs, span_to_tan_instances, animacy_instances):
            qg_instance.index_fields(self._question_model.vocab)
            qgen_input_tensors = move_to_device(
                Batch([qg_instance]).as_tensor_dict(),
                self._question_model._get_prediction_device())
            _, all_question_slots, question_probs = self._question_model.beam_decode(
                text = qgen_input_tensors["text"],
                predicate_indicator = qgen_input_tensors["predicate_indicator"],
                predicate_index = qgen_input_tensors["predicate_index"],
                max_beam_size = self._question_beam_size,
                min_beam_probability = self._question_minimum_threshold,
                clause_mode = self._clause_mode)

            verb_qa_instances = []
            question_slots_list = []
            for i in range(len(question_probs)):
                qa_instance = Instance({k: v for k, v in qa_instance_template.fields.items()})
                question_slots = {}
                for slot_name in self._question_to_span_model.get_slot_names():
                    slot_label = all_question_slots[slot_name][i]
                    question_slots[slot_name] = slot_label
                    slot_label_field = LabelField(slot_label, get_slot_label_namespace(slot_name))
                    qa_instance.add_field(slot_name, slot_label_field, self._question_to_span_model.vocab)
                question_slots_list.append(question_slots)
                verb_qa_instances.append(qa_instance)
            if len(verb_qa_instances) > 0:
                qa_outputs = self._question_to_span_model.forward_on_instances(verb_qa_instances)
                if self._animacy_model is not None or self._span_to_tan_model is not None:
                    all_spans = list(set([s for qa_output in qa_outputs for s, p in qa_output["spans"] if p >= self._span_minimum_threshold]))
                if self._animacy_model is not None:
                    animacy_instance.add_field("animacy_spans", ListField([SpanField(s.start(), s.end(), animacy_instance["text"]) for s in all_spans]), self._animacy_model.vocab)
                    animacy_output = self._animacy_model.forward_on_instance(animacy_instance)
                else:
                    animacy_output = None
                if self._span_to_tan_model is not None:
                    span_to_tan_instance.add_field("tan_spans", ListField([SpanField(s.start(), s.end(), span_to_tan_instance["text"]) for s in all_spans]))
                    span_to_tan_output = self._span_to_tan_model.forward_on_instance(span_to_tan_instance)
                else:
                    span_to_tan_output = None
            else:
                qa_outputs = []
                animacy_output = None
                span_to_tan_output = None

            qa_beam = []
            for question_slots, question_prob, qa_output in zip(question_slots_list, question_probs, qa_outputs):
                scored_spans = [(s, p) for s, p in qa_output["spans"] if p >= self._span_minimum_threshold]
                invalid_dict = {}
                if self._question_to_span_model.classifies_invalids():
                    invalid_dict["invalidProb"] = qa_output["invalid_prob"].item()
                for span, span_prob in scored_spans:
                    qa_beam.append({
                        "questionSlots": question_slots,
                        "questionProb": question_prob,
                        **invalid_dict,
                        "span": [span.start(), span.end() + 1],
                        "spanProb": span_prob
                    })
            beam = { "qa_beam": qa_beam }
            if tan_output is not None:
                beam["tans"] = [
                    (self._tan_model.vocab.get_token_from_index(i, namespace = "tan-string-labels"), p)
                    for i, p in enumerate(tan_output["probs"].tolist())
                    if p >= self._tan_minimum_threshold
                ]
            if animacy_output is not None:
                beam["animacy"] = [
                    ([s.start(), s.end() + 1], p)
                    for s, p in zip(all_spans, animacy_output["probs"].tolist())
                ]
            if span_to_tan_output is not None:
                beam["span_tans"] = [
                    ([s.start(), s.end() + 1], [
                        (self._span_to_tan_model.vocab.get_token_from_index(i, namespace = "tan-string-labels"), p)
                        for i, p in enumerate(probs)
                        if p >= self._tan_minimum_threshold])
                    for s, probs in zip(all_spans, span_to_tan_output["probs"].tolist())
                ]
            verb_dicts.append({
                "verbIndex": qg_instance["metadata"]["verb_index"],
                "verbInflectedForms": qg_instance["metadata"]["verb_inflected_forms"],
                "beam": beam
            })
        return {
            "sentenceId": inputs["sentenceId"],
            "sentenceTokens": inputs["sentenceTokens"],
            "verbs": verb_dicts
        }

def main(question_model_path: str,
         question_to_span_model_path: str,
         tan_model_path: str,
         span_to_tan_model_path: str,
         animacy_model_path: str,
         cuda_device: int,
         input_file: str,
         output_file: str,
         span_min_prob: float,
         question_min_prob: float,
         tan_min_prob: float,
         question_beam_size: int,
         clause_mode: bool) -> None:
    clause_mode = True
    print("Checking device...", flush = True)
    check_for_gpu(cuda_device)
    print("Loading models...", flush = True)
    pipeline = QFirstPipeline(
        question_model_archive = load_archive_from_folder(question_model_path, cuda_device = cuda_device, weights_file = os.path.join(question_model_path, "best.th")),
        question_to_span_model_archive = load_archive_from_folder(question_to_span_model_path, cuda_device = cuda_device, weights_file = os.path.join(question_to_span_model_path, "best.th")),
        tan_model_archive = load_archive_from_folder(tan_model_path, cuda_device = cuda_device, weights_file = os.path.join(tan_model_path, "best.th")) if tan_model_path is not None else None,
        span_to_tan_model_archive = load_archive_from_folder(span_to_tan_model_path, cuda_device = cuda_device, weights_file = os.path.join(span_to_tan_model_path, "best.th")) if span_to_tan_model_path is not None else None,
        animacy_model_archive = load_archive_from_folder(animacy_model_path, cuda_device = cuda_device, weights_file = os.path.join(animacy_model_path, "best.th")) if animacy_model_path is not None else None,
        question_minimum_threshold = question_min_prob,
        span_minimum_threshold = span_min_prob,
        tan_minimum_threshold = tan_min_prob,
        question_beam_size = question_beam_size,
        clause_mode = clause_mode)
    print("Models loaded. Running...", flush = True)
    if output_file is None:
        for line in read_lines(cached_path(input_file)):
            input_json = json.loads(line)
            output_json = pipeline.predict(input_json)
            print(json.dumps(output_json))
    else:
        with open(output_file, 'w', encoding = 'utf8') as out:
            for line in read_lines(cached_path(input_file)):
                input_json = json.loads(line)
                output_json = pipeline.predict(input_json)
                print(".", end = "", flush = True)
                print(json.dumps(output_json), file = out)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description = "Run the answer-first pipeline")
    parser.add_argument('--question', type=str, help = "Path to question generator model serialization dir.")
    parser.add_argument('--question_to_span', type=str, help = "Path to question-to-span model serialization dir.")
    parser.add_argument('--tan', type=str, help = "Path to TAN model serialization dir.", default = None)
    parser.add_argument('--span_to_tan', type=str, help = "Path to Span-to-TAN model serialization dir.", default = None)
    parser.add_argument('--animacy', type=str, help = "Path to animacy model archive serialization dir.", default = None)
    parser.add_argument('--cuda_device', type=int, default=-1)
    parser.add_argument('--input_file', type=str)
    parser.add_argument('--output_file', type=str, default = None)
    parser.add_argument('--question_min_prob', type=float, default = question_minimum_threshold_default)
    parser.add_argument('--span_min_prob', type=float, default = span_minimum_threshold_default)
    parser.add_argument('--tan_min_prob', type=float, default = tan_minimum_threshold_default)
    parser.add_argument('--question_beam_size', type=int, default = question_beam_size_default)
    parser.add_argument('--clause_mode', type=bool, default = False)

    args = parser.parse_args()
    main(question_model_path = args.question,
         question_to_span_model_path = args.question_to_span,
         tan_model_path = args.tan,
         span_to_tan_model_path = args.span_to_tan,
         animacy_model_path = args.animacy,
         cuda_device = args.cuda_device,
         input_file = args.input_file,
         output_file = args.output_file,
         span_min_prob = args.span_min_prob,
         question_min_prob = args.question_min_prob,
         tan_min_prob = args.tan_min_prob,
         question_beam_size = args.question_beam_size,
         clause_mode = args.clause_mode)
