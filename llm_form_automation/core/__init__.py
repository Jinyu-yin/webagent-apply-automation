# Core modules for application automation

from .application_state_machine import (
    ApplicationStateMachine,
    ProcessStatus,
    get_current_stage,
    is_waiting_for_user,
    get_expected_user_action
)

from .application_api import (
    ApplicationAPI,
    handle_apply_request
)

from .response_status import (
    ResponseStatus,
    analyzing,
    need_input,
    ready_to_fill,
    filling,
    fill_completed,
    need_iteration,
    iterating,
    pending_review,
    user_modified,
    completed,
    error,
    is_terminal_status,
    is_waiting_user
)

from .filling_executor import (
    FillingExecutor,
    run_filling,
    run_iteration,
    apply_modifications
)

from .field_extractor import FieldExtractor
from .field_matcher import FieldMatcher
from .application_pipeline import ApplicationPipeline, create_pipeline

__all__ = [
    # State machine
    'ApplicationStateMachine',
    'ProcessStatus',
    'get_current_stage',
    'is_waiting_for_user',
    'get_expected_user_action',
    
    # API
    'ApplicationAPI',
    'handle_apply_request',
    
    # Response status
    'ResponseStatus',
    'analyzing',
    'need_input',
    'ready_to_fill',
    'filling',
    'fill_completed',
    'need_iteration',
    'iterating',
    'pending_review',
    'user_modified',
    'completed',
    'error',
    'is_terminal_status',
    'is_waiting_user',
    
    # Filling executor
    'FillingExecutor',
    'run_filling',
    'run_iteration',
    'apply_modifications',
    
    # Pipeline
    'FieldExtractor',
    'FieldMatcher',
    'ApplicationPipeline',
    'create_pipeline',
]
