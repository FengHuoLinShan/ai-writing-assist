from modules.story._compat import alias_module as _alias

_alias(
    __name__,
    "modules.story.facade",
    export_module_name="modules.story.outline_state.facade",
)
