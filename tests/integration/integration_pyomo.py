from pyomo.environ import ConcreteModel, Set, Var, NonNegativeReals, Block, Constraint, Objective, SolverFactory, minimize


if __name__ == "__main__":

    # Create a concrete model
    model = ConcreteModel()

    # Define a set with three indices
    model.I = Set(initialize=[1, 2, 3])

    # Define variables indexed by the set (non-negative real numbers)
    model.x = Var(model.I, domain=NonNegativeReals)

    # Create a block to contain related constraints
    model.block1 = Block()

    # Define a constraint rule inside the block:
    # For each index i in set I, enforce x[i] >= i
    def constraint_rule(b, i):
        return model.x[i] >= i

    # Add the constraint to the block over the entire set I
    model.block1.cons = Constraint(model.I, rule=constraint_rule)

    # Define the objective: minimize the sum of x[i] over I
    def obj_rule(model):
        return sum(model.x[i] for i in model.I)
    model.obj = Objective(rule=obj_rule, sense=minimize)

    # Create the HiGHS solver and solve the model
    opt = SolverFactory('appsi_highs')
    results = opt.solve(model, tee=True)

    # Display the results
    model.display()
