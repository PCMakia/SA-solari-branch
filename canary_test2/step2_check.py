import os

def run_step_two():
    assert os.path.exists("step1_complete.txt"), "Step 1 artifact missing!"
    print("CANARY TEST 2 PASSED: Step 2 completed successfully.")

if __name__ == "__main__":
    run_step_two()
