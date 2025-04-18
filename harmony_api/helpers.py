"""
MIT License

Copyright (c) 2023 Ulster University (https://www.ulster.ac.uk).
Project: Harmony (https://harmonydata.ac.uk)
Maintainer: Thomas Wood (https://fastdatascience.com)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import bz2
import json
import os
import pickle as pkl
import re
import requests
import uuid
from collections import OrderedDict
from typing import List, Callable
from io import BytesIO

import numpy as np

from harmony.matching.negator import negate
from harmony.schemas.requests.text import Instrument, Question
from harmony_api.constants import (
    GOOGLE_GECKO_MULTILINGUAL,
    GOOGLE_GECKO_003,
    OPENAI_3_LARGE,
    OPENAI_ADA_02,
    HUGGINGFACE_MPNET_BASE_V2,
    HUGGINGFACE_MINILM_L12_V2,
    AZURE_OPENAI_ADA_02,
    AZURE_OPENAI_3_LARGE, HUGGINGFACE_MENTAL_HEALTH_HARMONISATION_1,
)
from harmony_api.core.settings import get_settings
from harmony_api.services import azure_openai_embeddings
from harmony_api.services import google_embeddings
from harmony_api.services import hugging_face_embeddings
from harmony_api.services import openai_embeddings
from harmony_api.services.azure_openai_embeddings import (
    HARMONY_API_AVAILABLE_AZURE_OPENAI_MODELS_LIST,
)
from harmony_api.services.google_embeddings import (
    HARMONY_API_AVAILABLE_GOOGLE_MODELS_LIST,
)
from harmony_api.services.openai_embeddings import (
    HARMONY_API_AVAILABLE_OPENAI_MODELS_LIST,
)
from harmony_api.services.vectors_cache import VectorsCache

settings = get_settings()

dir_path = os.path.dirname(os.path.realpath(__file__))

# Cache
vectors_cache = VectorsCache()


def get_example_instruments() -> List[Instrument]:
    """Get example instruments"""

    example_instruments = []

    with open(
            str(os.getcwd()) + "/example_questionnaires.json", "r", encoding="utf-8"
    ) as file:
        for line in file:
            instrument = Instrument.model_validate_json(line)
            example_instruments.append(instrument)

    return example_instruments


def get_mhc_embeddings(model_name: str) -> tuple:
    """
    Get mhc embeddings.
    """

    mhc_questions = []
    mhc_all_metadata = []
    mhc_embeddings = np.zeros((0, 0))

    # Only return the MHC embeddings for the Hugging Face models
    if model_name not in [
        HUGGINGFACE_MPNET_BASE_V2["model"],
        HUGGINGFACE_MINILM_L12_V2["model"],
    ]:
        return mhc_questions, mhc_all_metadata, mhc_embeddings

    try:
        data_path = os.path.join(dir_path, "../mhc_embeddings")  # submodule

        with open(
                os.path.join(data_path, "mhc_questions.txt"), "r", encoding="utf-8"
        ) as file:
            for line in file:
                mhc_question = Question(question_text=line)
                mhc_questions.append(mhc_question)

        with open(
                os.path.join(data_path, "mhc_all_metadatas.json"), "r", encoding="utf-8"
        ) as file:
            for line in file:
                mhc_meta = json.loads(line)
                mhc_all_metadata.append(mhc_meta)

        with open(
                os.path.join(
                    data_path, f"mhc_embeddings_{model_name.replace('/', '-')}.npy"
                ),
                "rb",
        ) as file:
            mhc_embeddings = np.load(file, allow_pickle=True)
    except (Exception,) as e:
        print(f"Could not load MHC embeddings {str(e)}")

    return mhc_questions, mhc_all_metadata, mhc_embeddings


def get_catalogue_data_default() -> dict:
    """
    Get catalogue data default.

    Check if the files are available in the current directory, if not, download them from Azure Blob Storage.
    """

    all_questions = []
    all_instruments = []
    instrument_idx_to_question_idx = []

    # All questions
    all_questions_ever_seen_json = "all_questions_ever_seen.json"
    if os.path.isfile(all_questions_ever_seen_json):
        with open(all_questions_ever_seen_json, "r", encoding="utf-8") as file:
            all_questions = json.loads(file.read())
    else:
        if settings.AZURE_STORAGE_URL:
            with requests.get(
                    url=f"{settings.AZURE_STORAGE_URL}/catalogue_data/{all_questions_ever_seen_json}",
                    stream=True,
            ) as response:
                if response.ok:
                    buffer = BytesIO()
                    for chunk in response.iter_content(chunk_size=1024):
                        buffer.write(chunk)
                    all_questions = json.loads(buffer.getvalue().decode("utf-8"))
                    buffer.close()

    # Instrument index to question indexes
    instrument_idx_to_question_idxs_json = "instrument_idx_to_question_idxs.json"
    if os.path.isfile(instrument_idx_to_question_idxs_json):
        with open(instrument_idx_to_question_idxs_json, "r", encoding="utf-8") as file:
            instrument_idx_to_question_idx = json.loads(file.read())
    else:
        if settings.AZURE_STORAGE_URL:
            with requests.get(
                    url=f"{settings.AZURE_STORAGE_URL}/catalogue_data/{instrument_idx_to_question_idxs_json}",
                    stream=True,
            ) as response:
                if response.ok:
                    buffer = BytesIO()
                    for chunk in response.iter_content(chunk_size=1024):
                        buffer.write(chunk)
                    instrument_idx_to_question_idx = json.loads(
                        buffer.getvalue().decode("utf-8")
                    )
                    buffer.close()

    # All instruments
    all_instruments_preprocessed_json = "all_instruments_preprocessed.json"
    if os.path.isfile(all_instruments_preprocessed_json):
        with open(all_instruments_preprocessed_json, "r", encoding="utf-8") as file:
            for line in file:
                instrument = json.loads(line)
                all_instruments.append(instrument)
    else:
        if settings.AZURE_STORAGE_URL:
            with requests.get(
                    url=f"{settings.AZURE_STORAGE_URL}/catalogue_data/{all_instruments_preprocessed_json}",
                    stream=True,
            ) as response:
                if response.ok:
                    buffer = BytesIO()
                    for chunk in response.iter_content(chunk_size=1024):
                        buffer.write(chunk)
                    for line in buffer.getvalue().decode("utf-8").splitlines():
                        instrument = json.loads(line)
                        all_instruments.append(instrument)
                    buffer.close()

    return {
        "all_questions": all_questions,
        "all_instruments": all_instruments,
        "instrument_idx_to_question_idx": instrument_idx_to_question_idx,
    }


def get_catalogue_data_model_embeddings(model: dict) -> np.ndarray:
    """
    Get catalogue data model embeddings.

    Check if the file is available in the current directory, if not, download it from Azure Blob Storage.

    :param model: The model to download catalogue embeddings for.
    """

    all_embeddings_concatenated = np.array([])

    # Currently only "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2" is supported
    if model["model"] != HUGGINGFACE_MINILM_L12_V2["model"]:
        return all_embeddings_concatenated

    # Embeddings
    embeddings_filename = create_embeddings_filename_for_model(model)
    if os.path.isfile(embeddings_filename):
        with bz2.open(embeddings_filename, "rb") as f:
            all_embeddings_concatenated = pkl.load(f)
    else:
        if settings.AZURE_STORAGE_URL:
            decompressor_results = []
            decompressor = bz2.BZ2Decompressor()
            with requests.get(
                    url=f"{settings.AZURE_STORAGE_URL}/catalogue_data/{embeddings_filename}",
                    stream=True,
            ) as response:
                if response.ok:
                    for chunk in response.iter_content(chunk_size=1024):
                        decompressor_results.append(decompressor.decompress(chunk))
                        if decompressor.eof:
                            break
                    buffer = BytesIO(b"".join(decompressor_results))
                    all_embeddings_concatenated = pkl.load(buffer)
                    buffer.close()

    return all_embeddings_concatenated


def filter_catalogue_data(
        catalogue_data: dict,
        sources: List[str] | None = None,
        topics: List[str] | None = None,
        instrument_length_min: int | None = None,
        instrument_length_max: int | None = None,
) -> dict:
    """
    Filter catalogue data to only keep instruments with the sources.

    :param catalogue_data: Catalogue data.
    :param sources: Only keep instruments from sources.
    :param topics: Only keep instruments with these topics. Topics can be found in the metadata of each instrument.
    :param instrument_length_min: Only keep instruments with min number of questions.
    :param instrument_length_max: Only keep instruments with max number of questions.
    :return: The filtered catalogue data.
    """

    def normalize_text(text: str):
        text = re.sub(r"(?i)\b(?:the|a)\b", "", text).lower()
        text = re.sub(r"[^a-z0-9]", "", text.lower().strip())

        return text

    if not sources:
        sources = []
    if not topics:
        topics = []

    # If the value for any of these is less than 1, set it to 1
    if instrument_length_min and (instrument_length_min < 1):
        instrument_length_min = 1
    if instrument_length_max and (instrument_length_max < 1):
        instrument_length_max = 1

    # If min length is bigger than max length, set the min length to equal the max length
    if instrument_length_min and instrument_length_max:
        if instrument_length_min > instrument_length_max:
            instrument_length_min = instrument_length_max

    # Lowercase sources and topics
    sources_set = {x.strip().lower() for x in sources if x.strip()}
    topics_set = {x.strip().lower() for x in topics if x.strip()}

    # Create a dictionary with questions and their vectors
    question_normalized_to_vector: dict[str, List[float]] = {}
    for question, vector in zip(
            catalogue_data["all_questions"], catalogue_data["all_embeddings_concatenated"]
    ):
        question_normalized = normalize_text(question)
        if question_normalized not in question_normalized_to_vector:
            question_normalized_to_vector[question_normalized] = vector

    # Find instrument indexes to remove
    idxs_instruments_to_remove: List[int] = []
    for instrument_idx, catalogue_instrument in enumerate(
            catalogue_data["all_instruments"]
    ):
        questions_len = len(catalogue_instrument["questions"])

        # By min instrument questions length
        if instrument_length_min:
            if questions_len < instrument_length_min:
                idxs_instruments_to_remove.append(instrument_idx)
                continue

        # By max instrument questions length
        if instrument_length_max:
            if questions_len > instrument_length_max:
                idxs_instruments_to_remove.append(instrument_idx)
                continue

        # By sources
        if sources_set:
            if (
                    catalogue_instrument["metadata"]["source"].strip().lower()
                    not in sources_set
            ):
                idxs_instruments_to_remove.append(instrument_idx)
                continue

        # By topics
        if topics_set:
            not_found_topics_len = 0
            catalogue_instrument_topics: list[str] = catalogue_instrument[
                "metadata"
            ].get("topics", [])
            for topic in topics_set:
                if topic not in [
                    x.strip().lower() for x in catalogue_instrument_topics if x.strip()
                ]:
                    not_found_topics_len += 1
            if not_found_topics_len == len(topics_set):
                idxs_instruments_to_remove.append(instrument_idx)
                continue

    # Remove instruments
    for idx_instrument_to_remove in sorted(idxs_instruments_to_remove, reverse=True):
        del catalogue_data["all_instruments"][idx_instrument_to_remove]

    # Create an updated question to vectors dict to contain only questions from the remaining instrument questions
    updated_question_normalized_to_vector = OrderedDict()
    idx_question = 0
    for instrument in catalogue_data["all_instruments"]:
        questions = [x["question_text"] for x in instrument["questions"]]
        for question in questions:
            question_normalized = normalize_text(question)
            if question_normalized not in updated_question_normalized_to_vector:
                updated_question_normalized_to_vector[question_normalized] = {
                    "index": idx_question,
                    "original_question": question,
                    "vector": question_normalized_to_vector[question_normalized],
                }
                idx_question += 1

    # Update the embeddings
    catalogue_data["all_embeddings_concatenated"] = np.array(
        [x["vector"] for x in updated_question_normalized_to_vector.values()]
    )

    # Update all questions
    catalogue_data["all_questions"] = [
        x["original_question"] for x in updated_question_normalized_to_vector.values()
    ]

    # Recreate instrument index to question index
    catalogue_data["instrument_idx_to_question_idx"] = []
    for instrument in catalogue_data["all_instruments"]:
        questions_normalized = set(
            [normalize_text(x["question_text"]) for x in instrument["questions"]]
        )
        idxs_questions = [
            updated_question_normalized_to_vector[x]["index"]
            for x in questions_normalized
        ]
        catalogue_data["instrument_idx_to_question_idx"].append(idxs_questions)

    return catalogue_data


def check_model_availability(model: dict) -> bool:
    """
    Check model availability.
    """

    # Hugging Face
    if model["framework"] == "huggingface":
        # No checks required, always return True at the end of this function
        pass

    # OpenAI
    elif model["framework"] == "openai":
        if not settings.OPENAI_API_KEY:
            return False

        # Check model
        if model["model"] not in HARMONY_API_AVAILABLE_OPENAI_MODELS_LIST:
            return False

    # Azure OpenAI
    elif model["framework"] == "azure_openai":
        # Check model
        if model["model"] not in HARMONY_API_AVAILABLE_AZURE_OPENAI_MODELS_LIST:
            return False

    # Google
    elif model["framework"] == "google":
        if not google_embeddings.GOOGLE_APPLICATION_CREDENTIALS_DICT:
            return False

        # Check model
        if model["model"] not in HARMONY_API_AVAILABLE_GOOGLE_MODELS_LIST:
            return False

    return True


def get_cached_text_vectors(
        instruments: List[Instrument], model: dict, query: str | None = None
) -> dict[str, List[float]]:
    """
    Get cached text vectors.

    :param instruments: The instruments.
    :param query: The query.
    :param model: The model.
    """

    cached_text_vectors_dict: dict[str, List[float]] = {}
    for instrument in instruments:
        for question in instrument.questions:
            # Text
            question_text = question.question_text
            question_text_key = vectors_cache.generate_key(
                text=question_text,
                model_framework=model["framework"],
                model_name=model["model"],
            )
            if vectors_cache.has(question_text_key):
                cached_vector = vectors_cache.get(question_text_key)
                cached_text_vectors_dict[question_text] = cached_vector[question_text]

            # Negated text
            negated_text = negate(question_text, instrument.language)
            negated_text_key = vectors_cache.generate_key(
                text=negated_text,
                model_framework=model["framework"],
                model_name=model["model"],
            )
            if vectors_cache.has(negated_text_key):
                cached_vector = vectors_cache.get(negated_text_key)
                cached_text_vectors_dict[negated_text] = cached_vector[negated_text]

    # Get cached vector of query
    if query:
        query_key = vectors_cache.generate_key(
            text=query, model_framework=model["framework"], model_name=model["model"]
        )
        if vectors_cache.has(query_key):
            cached_vector = vectors_cache.get(query_key)
            cached_text_vectors_dict[query] = cached_vector[query]

    return cached_text_vectors_dict


def get_vectorisation_function_for_model(model: dict) -> Callable | None:
    """
    Get vectorisation function for model.

    :param model: The model.
    """

    vectorisation_function: Callable | None = None

    if (
            model["framework"] == HUGGINGFACE_MINILM_L12_V2["framework"]
            and model["model"] == HUGGINGFACE_MINILM_L12_V2["model"]
    ):
        vectorisation_function = (
            hugging_face_embeddings.get_hugging_face_embeddings_minilm_l12_v2
        )

    elif (
            model["framework"] == HUGGINGFACE_MPNET_BASE_V2["framework"]
            and model["model"] == HUGGINGFACE_MPNET_BASE_V2["model"]
    ):
        vectorisation_function = (
            hugging_face_embeddings.get_hugging_face_embeddings_mpnet_base_v2
        )

    elif (
            model["framework"] == HUGGINGFACE_MPNET_BASE_V2["framework"]
            and model["model"] == HUGGINGFACE_MENTAL_HEALTH_HARMONISATION_1["model"]
    ):
        vectorisation_function = (
            hugging_face_embeddings.get_hugging_face_embeddings_harmonydata_mental_health_harmonisation_1
        )

    elif (
            model["framework"] == OPENAI_ADA_02["framework"]
            and model["model"] == OPENAI_ADA_02["model"]
    ):
        vectorisation_function = openai_embeddings.get_openai_embeddings_ada_02
    elif (
            model["framework"] == OPENAI_3_LARGE["framework"]
            and model["model"] == OPENAI_3_LARGE["model"]
    ):
        vectorisation_function = openai_embeddings.get_openai_embeddings_3_large
    elif (
            model["framework"] == AZURE_OPENAI_3_LARGE["framework"]
            and model["model"] == AZURE_OPENAI_3_LARGE["model"]
    ):
        vectorisation_function = (
            azure_openai_embeddings.get_azure_openai_embeddings_3_large
        )
    elif (
            model["framework"] == AZURE_OPENAI_ADA_02["framework"]
            and model["model"] == AZURE_OPENAI_ADA_02["model"]
    ):
        vectorisation_function = (
            azure_openai_embeddings.get_azure_openai_embeddings_ada_02
        )
    elif (
            model["framework"] == GOOGLE_GECKO_MULTILINGUAL["framework"]
            and model["model"] == GOOGLE_GECKO_MULTILINGUAL["model"]
    ):
        vectorisation_function = (
            google_embeddings.get_google_embeddings_gecko_multilingual
        )
    elif (
            model["framework"] == GOOGLE_GECKO_003["framework"]
            and model["model"] == GOOGLE_GECKO_003["model"]
    ):
        vectorisation_function = google_embeddings.get_google_embeddings_gecko_003

    return vectorisation_function


def assign_missing_ids_to_instruments(
        instruments: List[Instrument],
) -> List[Instrument]:
    """
    Assign missing IDs to instruments.
    """

    # Assign any missing IDs to instruments
    for instrument in instruments:
        if instrument.file_id is None:
            instrument.file_id = uuid.uuid4().hex
        if instrument.instrument_id is None:
            instrument.instrument_id = uuid.uuid4().hex

    return instruments


def create_embeddings_filename_for_model(model: dict) -> str:
    """
    This function will create the embeddings filename for a model.

    :param model: The model.
    """

    filename = f"{model['framework']}_{model['model']}"
    filename = filename.replace("-", "_")
    filename = filename.replace("/", "_")
    filename = f"{filename}_embeddings_all_float16.pkl.bz2"

    return filename
