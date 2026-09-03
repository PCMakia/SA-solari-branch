# INTENTIONAL BUG (canary-2): Missing closing parenthesis on open().
def run_step_one():
    print("Canary-2 step 1 starting...")
    with open("step1_complete.txt", "w" as f:
        f.write("CANARY2-DONE")

if __name__ == "__main__":
    run_step_one()
