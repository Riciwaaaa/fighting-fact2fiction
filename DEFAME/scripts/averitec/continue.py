from infact.eval.continute import continue_evaluation
from multiprocessing import set_start_method

experiment_dir = "out/averitec/infact/gemini_35_flash/2026-06-30_04-34"

if __name__ == '__main__':  # evaluation uses multiprocessing
    set_start_method("spawn")
    continue_evaluation(experiment_dir=experiment_dir)
