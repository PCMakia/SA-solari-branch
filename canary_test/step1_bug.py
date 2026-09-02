# INTENTIONAL BUG: Missing closing parenthesis on line 5
def run_step_one():
    print("Step 1 starting...")
    print("Executing critical canary task"  # Missing closing parenthesis
    with open("step1_complete.txt", "w") as f:
        f.write("DONE")

if __name__ == "__main__":
    run_step_one()