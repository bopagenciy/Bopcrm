RECOGNIZED_SOURCE_APPS = frozenset({
    "bop_clients",
    "bop_social",
    "bop_erp",
    "bop_chatbot",
    "bop_assistant",
})

BOP_SOURCE_APP_CHOICES = tuple(
    (app, app) for app in sorted(RECOGNIZED_SOURCE_APPS)
)
