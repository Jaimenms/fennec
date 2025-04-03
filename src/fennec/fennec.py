from argparse import ArgumentParser
import logging
import json

import pyomo.environ as pyo

from fennec import models
from fennec.utils import convert_none_keys, get_detailed_results


def run(
        data: dict = None,
        solver_name: str = "appsi_highs",
        mip_abs_gap: float = 0.0001,
        mip_rel_gap: float = 0.001,
        time_limit: int = 20,
        model: pyo.AbstractModel = None
):

    if data is None:
        data = {}

    solver = pyo.SolverFactory(solver_name)
    solver.options["mip_abs_gap"] = mip_abs_gap
    solver.options["mip_rel_gap"] = mip_rel_gap
    solver.options["time_limit"] = time_limit

    if not solver.available():
        logging.error("Solver not available")
        exit(1)

    if model is None:
        model = models.SmartHome()

    instance = model.create_instance(data)

    results = solver.solve(instance, tee=False, load_solutions=False)

    if (results.solver.termination_condition == pyo.TerminationCondition.feasible):
        instance.solutions.load_from(results)
    else:
        logging.error("Failed to run optimization")

    logging.debug("Solver Status:", results.solver.status)
    logging.debug("Termination Condition:", results.solver.termination_condition)

    return results, instance


if __name__ == "__main__":

    parser = ArgumentParser(description="Fennec Energy Optimizer")

    parser.add_argument("--input", help="Path to file with data")

    parser.add_argument("--output", help="Path to file with results")

    args = parser.parse_args()

    with open(args.file, "r") as f:
        data_json = json.load(f)

    data = convert_none_keys(data_json)

    results, instance = run(data)

    detailed_results = get_detailed_results(results)

    with open(args.output, "w") as f:
        json.dump(detailed_results, f)

