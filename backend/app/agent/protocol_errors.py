"""Fixed, content-free observations attached to unchanged protocol exceptions."""

from enum import Enum


class ProtocolStage(Enum):
    PROVIDER_PACKET = "provider_packet"
    PROVIDER_DELTA = "provider_delta"
    PROVIDER_USAGE = "provider_usage"
    STREAM_AGGREGATE = "stream_aggregate"
    TOOL_AGGREGATE = "tool_aggregate"
    DSML_PARSE = "dsml_parse"
    DSML_RECONCILE = "dsml_reconcile"
    SCHEMA_VALIDATION = "schema_validation"

    def __str__(self) -> str:
        return self.value


class ProtocolCode(Enum):
    PACKET_JSON_INVALID = ("provider_packet_json_invalid", ProtocolStage.PROVIDER_PACKET)
    PACKET_NOT_OBJECT = ("provider_packet_not_object", ProtocolStage.PROVIDER_PACKET)
    PROVIDER_STREAM_ERROR = ("provider_stream_error", ProtocolStage.PROVIDER_PACKET)
    USAGE_PACKET_TYPE = ("provider_usage_packet_type", ProtocolStage.PROVIDER_USAGE)
    USAGE_COUNTS_TYPE = ("provider_usage_counts_type", ProtocolStage.PROVIDER_USAGE)
    USAGE_VALUES_INVALID = ("provider_usage_values_invalid", ProtocolStage.PROVIDER_USAGE)
    CHOICES_TYPE = ("provider_choices_type", ProtocolStage.PROVIDER_DELTA)
    CHOICE_TYPE = ("provider_choice_type", ProtocolStage.PROVIDER_DELTA)
    FINISH_REASON_TYPE = ("provider_finish_reason_type", ProtocolStage.PROVIDER_DELTA)
    CONTENT_TYPE = ("provider_content_type", ProtocolStage.PROVIDER_DELTA)
    REASONING_TYPE = ("provider_reasoning_type", ProtocolStage.PROVIDER_DELTA)
    TOOL_CALLS_TYPE = ("provider_tool_calls_type", ProtocolStage.PROVIDER_DELTA)
    TOOL_INDEX_TYPE = ("provider_tool_index_type", ProtocolStage.PROVIDER_DELTA)
    TOOL_INDEX_NEGATIVE = ("provider_tool_index_negative", ProtocolStage.PROVIDER_DELTA)
    TOOL_ID_TYPE = ("provider_tool_id_type", ProtocolStage.PROVIDER_DELTA)
    TOOL_FUNCTION_TYPE = ("provider_tool_function_type", ProtocolStage.PROVIDER_DELTA)
    TOOL_NAME_TYPE = ("provider_tool_name_type", ProtocolStage.PROVIDER_DELTA)
    TOOL_ARGUMENTS_TYPE = ("provider_tool_arguments_type", ProtocolStage.PROVIDER_DELTA)
    CHUNK_TYPE = ("assistant_chunk_type", ProtocolStage.STREAM_AGGREGATE)
    STREAM_EMPTY = ("model_stream_empty", ProtocolStage.STREAM_AGGREGATE)
    RESPONSE_EMPTY = ("model_response_empty", ProtocolStage.STREAM_AGGREGATE)
    SUMMARY_FINISH_TYPE = ("summary_finish_reason_type", ProtocolStage.STREAM_AGGREGATE)
    FRAGMENT_INDEX_INVALID = ("tool_fragment_index_invalid", ProtocolStage.TOOL_AGGREGATE)
    TOOL_IDENTITY_MISSING = ("tool_identity_missing", ProtocolStage.TOOL_AGGREGATE)
    TOOL_JSON_INVALID = ("tool_arguments_json_invalid", ProtocolStage.TOOL_AGGREGATE)
    TOOL_NOT_OBJECT = ("tool_arguments_not_object", ProtocolStage.TOOL_AGGREGATE)
    TOOL_IDS_DUPLICATED = ("tool_ids_duplicated", ProtocolStage.TOOL_AGGREGATE)
    TOOL_SCHEMA_INVALID = ("tool_arguments_schema_invalid", ProtocolStage.SCHEMA_VALIDATION)
    DSML_ARGUMENT_UNKNOWN = ("dsml_argument_unknown", ProtocolStage.DSML_RECONCILE)
    DSML_ALIAS_CONFLICT = ("dsml_argument_alias_conflict", ProtocolStage.DSML_RECONCILE)
    DSML_ATTRIBUTE_DUPLICATED = ("dsml_attribute_duplicated", ProtocolStage.DSML_PARSE)
    DSML_STRING_ATTRIBUTE_INVALID = ("dsml_string_attribute_invalid", ProtocolStage.DSML_PARSE)
    DSML_NUMBER_NOT_FINITE = ("dsml_number_not_finite", ProtocolStage.DSML_PARSE)
    DSML_INVOKE_SEQUENCE_INVALID = ("dsml_invoke_sequence_invalid", ProtocolStage.DSML_PARSE)
    DSML_TOOL_NAME_MISSING = ("dsml_tool_name_missing", ProtocolStage.DSML_PARSE)
    DSML_PARAMETER_SEQUENCE_INVALID = ("dsml_parameter_sequence_invalid", ProtocolStage.DSML_PARSE)
    DSML_PARAMETER_NAME_INVALID = ("dsml_parameter_name_invalid", ProtocolStage.DSML_PARSE)
    DSML_PARAMETERS_INVALID = ("dsml_parameters_invalid", ProtocolStage.DSML_PARSE)
    DSML_BLOCK_INVALID = ("dsml_block_invalid", ProtocolStage.DSML_PARSE)
    DSML_WRAPPERS_AMBIGUOUS = ("dsml_wrappers_ambiguous", ProtocolStage.DSML_PARSE)
    DSML_OUTSIDE_WRAPPER = ("dsml_outside_wrapper", ProtocolStage.DSML_PARSE)
    DSML_INCOMPLETE = ("dsml_incomplete", ProtocolStage.DSML_PARSE)
    DSML_COUNT_MISMATCH = ("dsml_call_count_mismatch", ProtocolStage.DSML_RECONCILE)
    DSML_TOOL_UNKNOWN = ("dsml_tool_unknown", ProtocolStage.DSML_RECONCILE)
    DSML_NAME_MISMATCH = ("dsml_tool_name_mismatch", ProtocolStage.DSML_RECONCILE)
    DSML_ID_MISSING = ("dsml_structured_id_missing", ProtocolStage.DSML_RECONCILE)
    DSML_NOT_OBJECT = ("dsml_structured_arguments_not_object", ProtocolStage.DSML_RECONCILE)
    DSML_REQUIRED_MISSING = ("dsml_arguments_missing", ProtocolStage.DSML_RECONCILE)
    DSML_STRUCTURED_ARGUMENT_UNKNOWN = ("dsml_structured_argument_unknown", ProtocolStage.DSML_RECONCILE)
    DSML_IDS_DUPLICATED = ("dsml_ids_duplicated", ProtocolStage.DSML_RECONCILE)

    @property
    def text(self) -> str:
        return self.value[0]

    @property
    def stage(self) -> ProtocolStage:
        return self.value[1]

    def __str__(self) -> str:
        return self.text


def mark[E: Exception](error: E, code: ProtocolCode) -> E:
    """Return the identical exception; do not inspect or retain its raw inputs."""
    if type(code) is not ProtocolCode:
        raise TypeError("Protocol observation requires a fixed code enum")
    error.__dict__["_sqlchat_protocol_code"] = code
    return error


def protocol_code(error: BaseException) -> ProtocolCode | None:
    value: object = error.__dict__.get("_sqlchat_protocol_code")
    return value if type(value) is ProtocolCode else None
