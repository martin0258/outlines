"""A bot that uses an LLM to write unit tests under coverage conditions.

It prompts an LLM to complete the body of a test function for a given function.
The coverage of the LLM-completed test function is computed and, if full
coverage is not achieved, the LLM is prompted again but this time with the
line numbers of the source lines missing coverage.

N.B. This implementation is very naive and does not, for example, constrain or
guide the output of the LLM such that it always produces valid code or tests.
It is only for demonstration purposes.

You may need to install the following packages:
- coverage
- openai (optional)
- tiktoken (optional)

"""
import importlib
import inspect
import sys
from textwrap import dedent
from typing import List

import coverage

import outlines.models as models
import outlines.text as text


def get_missing_coverage_lines(code: str):
    cov = coverage.Coverage(branch=True)
    cov.erase()

    # Since `target_code` is now a Python function, consider evaluating the code
    # instead of creating a python file and loading it.
    modname = "test_mod"
    with open(modname + ".py", "wb") as f:
        f.write(code.encode("utf-8"))

    cov.start()
    try:
        mod = sys.modules.get(modname, None)
        if mod:
            mod = importlib.reload(mod)
        else:
            mod = importlib.import_module(modname)
    finally:
        cov.stop()

    analysis = cov._analyze(mod)

    return sorted(analysis.missing)


def collect_test_functions(string):
    """Collects the names of the test functions in a given string.

      Args:
        string: The string to collect the test functions from.

      Returns:
        A list of the names of the test functions.

    (This was generated by Bard!)
    """

    # Split the string into lines.
    lines = string.splitlines()

    # Create a list to store the test function names.
    test_function_names = []

    # Iterate over the lines, looking for lines that start with the `def` keyword.
    for line in lines:
        if line.startswith("def test"):
            # Get the name of the test function from the line.
            test_function_name = line.split("def")[1].split("(")[0].strip()

            # Add the test function name to the list.
            test_function_names.append(test_function_name)

    # Return the list of test function names.
    return test_function_names


@text.prompt
def construct_prompt(target_code: str):
    """The Python module code is as follows:

    {{ target_code }}

    Print only the code for a completed version of the following Python function named \
    `test_some_function` that attains full coverage over the Python module code above:

    def test_some_function():
    """


@text.prompt
def construct_prompt_test_code(target_code: str, test_code, lines: List[int]):
    """The Python module code is as follows:

    {{ target_code }}

    Print only the code for a completed version of the following Python function named \
    `test_some_function` that attains coverage for lines {{ lines | join(" and ") }} in the Python \
    module code above:

    {{ test_code }}
    """


def query(completer, target_code: str, test_code: str, lines):
    """Sample a query completion."""
    if test_code == "":
        prompt = construct_prompt(target_code)
    else:
        prompt = construct_prompt_test_code(target_code, test_code, lines)

    response = completer(prompt)

    return prompt, response


def get_missing_lines_for_completion(target_code, response):
    """Get the missing lines for the given completion."""

    def create_call(name):
        return dedent(
            f"""
    try:
        {name}()
    except AssertionError:
        pass"""
        )

    test_function_names = collect_test_functions(response)

    if not test_function_names:
        raise SyntaxError()

    run_statements = "\n".join([create_call(fname) for fname in test_function_names])

    c1 = f"""
{target_code}

{response}

{run_statements}
    """

    # Get missing coverage lines on the generated code,
    # remove the lines that correspond to the tests.
    lines = get_missing_coverage_lines(c1)
    lines = [str(ln) for ln in lines if ln < target_code.count("\n")]
    return lines


#
# The following are the functions to be tested:
#
def some_function(x, y):
    if x < 0:
        z = y - x
    else:
        z = y + x

    if z > y:
        return True

    return False


def some_other_function(x: int, y: int) -> bool:
    z = 0
    for i in range(x):
        if x < 3:
            z = y - x
        else:
            z = y + x

    if z > y:
        return True

    return False


#
# The testing loop:
#
target_code_examples = [some_function, some_other_function]
dialogs = []
n_coverage_attempts = 5

completer = models.text_completion.openai("gpt-3.5-turbo")


for target_function in target_code_examples:
    target_code = inspect.getsource(target_function)
    target_dialog = []
    test_code = ""
    lines: list = []
    #
    # Make `n_coverage_attempts`-many attempts at obtaining full coverage
    #
    for i in range(n_coverage_attempts):
        prompt, test_code = query(completer, target_code, test_code, lines)

        print(f"\nATTEMPT: {i}\n")
        print(f"PROMPT:\n{prompt.strip()}\n")
        print(f"RESPONSE:\n{test_code.strip()}\n")

        target_dialog.append((target_code, prompt, test_code))

        try:
            lines = get_missing_lines_for_completion(target_code, test_code)

            if len(lines) == 0:
                break
        except SyntaxError:
            test_code = ""

    dialogs.append([target_code, target_dialog])
