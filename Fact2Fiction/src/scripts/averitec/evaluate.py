from infact.eval.evaluate import evaluate
from multiprocessing import set_start_method

variant = "dev"

if __name__ == '__main__':  # evaluation uses multiprocessing
    set_start_method("spawn")
    evaluate(
        llm="minimax_m3",
        tools_config=dict(searcher=dict(
            search_engine_config=dict(
                averitec_kb=dict(variant=variant),
            ),
            limit_per_search=5
        )),
        fact_checker_kwargs=dict(
            procedure_variant="infact",
            max_iterations=3,
            max_result_len=64_000,  # characters
        ),
        llm_kwargs=dict(thinking_effort="adaptive"),
        benchmark_name="averitec",
        benchmark_kwargs=dict(variant=variant),
        n_samples=5,
        random_sampling=False,
        print_log_level="info",
        n_workers=1,
    )
