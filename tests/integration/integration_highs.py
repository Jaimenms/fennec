from pyomo import environ as pe


if __name__ == "__main__":

    # 1) Create the model
    model = pe.ConcreteModel()

    # 2) Define decision variables: x, y ≥ 0
    model.x = pe.Var(domain=pe.NonNegativeReals)
    model.y = pe.Var(domain=pe.NonNegativeReals)

    # 3) Objective: minimize x + 2y
    model.obj = pe.Objective(expr=model.x + 2 * model.y, sense=1)  # 1 = minimize

    # 4) Constraints
    model.c1 = pe.Constraint(expr=model.x + model.y >= 5)  # x + y ≥ 5
    model.c2 = pe.Constraint(expr=model.x - model.y <= 2)  # x - y ≤ 2

    # 5) Solve with HiGHS
    solver = pe.SolverFactory("appsi_highs")

    print(print(solver.available()))
    results = solver.solve(model, tee=False)

    # 6) Display results
    print("Solver Status:", results.solver.status)
    print("Termination Condition:", results.solver.termination_condition)

    print(f"x = {model.x.value:.2f}")
    print(f"y = {model.y.value:.2f}")
    print(f"Objective Value = {model.obj():.2f}")
