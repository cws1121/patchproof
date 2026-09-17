"""Small, intentionally public repair fixtures; not a SWE-bench substitute."""

from copy import deepcopy

TASKS = {
    "shipping": {
        "title": "Free shipping at the exact threshold",
        "ticket": "SHOP-104",
        "file": "commerce/shipping.py",
        "function": "shipping_fee",
        "args": ["total", "threshold", "fee"],
        "description": "Customers with an order total equal to the free-shipping threshold are still charged. Orders at or above the threshold must ship free; lower totals pay the configured fee. Inputs are nonnegative integers.",
        "buggy": "fee if total <= threshold else 0",
        "correct": "fee if total < threshold else 0",
        "overfit": "0",
        "visible": [([50, 50, 8], 0), ([100, 50, 8], 0)],
        "holdout": [
            ([0, 50, 8], 8),
            ([49, 50, 8], 8),
            ([51, 50, 8], 0),
            ([80, 100, 15], 15),
            ([100, 100, 15], 0),
            ([0, 0, 8], 0),
            ([10, 50, 0], 0),
            ([999, 1000, 3], 3),
        ],
        "lesson": "A patch that returns zero passes the reported examples but breaks paid shipping. Held-out regression cases catch this shortcut.",
    },
    "pagination": {
        "title": "The last partial page disappears",
        "ticket": "API-218",
        "file": "api/pagination.py",
        "function": "page_count",
        "args": ["total", "page_size"],
        "description": "Pagination drops a partially filled final page. Return the ceiling of total divided by page_size. Empty results have zero pages. total is a nonnegative integer; page_size is a positive integer.",
        "buggy": "total // page_size",
        "correct": "(total + page_size - 1) // page_size",
        "overfit": "total // page_size + 1",
        "visible": [([11, 10], 2), ([21, 10], 3)],
        "holdout": [
            ([0, 10], 0),
            ([10, 10], 1),
            ([20, 10], 2),
            ([1, 10], 1),
            ([99, 10], 10),
            ([100, 10], 10),
            ([5, 1], 5),
            ([7, 3], 3),
        ],
        "lesson": "Adding one fixes partial pages, but overcounts exact multiples and empty results. The validation gate must preserve those behaviors.",
    },
    "access": {
        "title": "Owners cannot edit their own documents",
        "ticket": "AUTH-031",
        "file": "permissions/access.py",
        "function": "can_edit",
        "args": ["owner_id", "actor_id", "is_admin"],
        "description": "Document owners are denied editing unless they are also administrators. Allow access when the actor owns the document OR is an administrator. Return a boolean. IDs are integers; is_admin is a boolean.",
        "buggy": "owner_id == actor_id and is_admin",
        "correct": "owner_id == actor_id or is_admin",
        "overfit": "True",
        "visible": [([7, 7, False], True), ([7, 9, True], True)],
        "holdout": [
            ([7, 9, False], False),
            ([0, 0, False], True),
            ([1, 1, True], True),
            ([2, 1, False], False),
            ([99, 0, True], True),
            ([3, 3, False], True),
            ([4, 5, False], False),
            ([4, 5, True], True),
        ],
        "lesson": "Always allowing access fixes the reported denial but creates a permission regression. Passing a bug reproduction is not sufficient.",
    },
    "retry": {
        "title": "Retry backoff grows linearly",
        "ticket": "OPS-072",
        "file": "workers/retry.py",
        "function": "retry_delay",
        "args": ["attempt", "base", "cap"],
        "description": "Retry delay should be exponential: base multiplied by 2 to the power of attempt, capped at cap. attempt starts at zero and ranges from 0 to 6; base and cap are nonnegative integers below 1000.",
        "buggy": "min(base * attempt, cap)",
        "correct": "min(base * (2 ** attempt), cap)",
        "overfit": "base * (2 ** attempt)",
        "visible": [([0, 2, 20], 2), ([2, 2, 20], 8)],
        "holdout": [
            ([4, 2, 20], 20),
            ([6, 10, 100], 100),
            ([1, 2, 20], 4),
            ([3, 2, 20], 16),
            ([0, 50, 10], 10),
            ([5, 0, 20], 0),
            ([5, 5, 0], 0),
            ([6, 1, 100], 64),
        ],
        "lesson": "Correct growth without the cap still passes small examples. Operational limits need their own regression tests.",
    },
}


def get_task(task_id):
    if task_id not in TASKS:
        raise ValueError("Unknown task")
    return deepcopy(TASKS[task_id])


def source(task, expression=None):
    return f"def {task['function']}({', '.join(task['args'])}):\n    return {expression or task['buggy']}\n"


def public_tasks():
    return [
        {
            "id": k,
            **{
                field: t[field]
                for field in (
                    "title",
                    "ticket",
                    "file",
                    "function",
                    "description",
                    "args",
                    "lesson",
                )
            },
            "source": source(t),
            "visible_tests": t["visible"],
            "holdout_count": len(t["holdout"]),
        }
        for k, t in TASKS.items()
    ]
