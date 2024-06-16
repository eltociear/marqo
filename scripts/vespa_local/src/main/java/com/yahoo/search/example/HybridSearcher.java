package com.yahoo.search.example;
import com.yahoo.component.chain.dependencies.Before;
import com.yahoo.component.chain.dependencies.After;
import com.yahoo.component.chain.dependencies.Provides;
import com.yahoo.search.Query;
import com.yahoo.search.Result;
import com.yahoo.search.Searcher;
import com.yahoo.search.result.HitGroup;
import com.yahoo.search.searchchain.Execution;
import com.yahoo.search.searchchain.AsyncExecution;
import com.yahoo.search.result.FeatureData;
import com.yahoo.search.result.Hit;
import com.yahoo.net.URI;
import java.util.HashMap;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.lang.InterruptedException;
import java.util.concurrent.ExecutionException;
// import org.apache.logging.log4j.Logger;
// import org.apache.logging.log4j.LogManager;
//import org.slf4j.Logger;
//import org.slf4j.LoggerFactory;

/**
 * This searcher takes the YQL for both a lexical and tensor search from the query,
 * Creates 2 clone queries
 *
 */
@Before("ExternalYql")
@Provides("HybridReRanking")
public class HybridSearcher extends Searcher {

    // Logger logger = LogManager.getLogger(HybridSearcher.class);
    // Logger logger = LoggerFactory.getLogger(HybridSearcher.class);

    private static String MATCH_FEATURES_FIELD = "matchfeatures";

    @Override
    public Result search(Query query, Execution execution) {

        // Query Properties to implement
        // hybrid.retrievalMethod
        // hybrid.rankingMethod
        // hybrid.rrf_k
        // hybrid.alpha
        // TODO: add score modifiers query_features
        // yql.tensor
        // yql.lexical
        // ranking methods are inherent to the SCHEMA, not the query! So I don't need to pass it

        // Retrieval methods: Disjunction, embedding_similarity, bm25
        // Ranking methods: RRF, normalize_linear, embedding_similarity, bm25

        // Questions:
            // can this 1 searcher handle all 12 combinations?
            // should we have different searchers per retrieval method? 12 searchers?
            // can retrieval and ranking methods be passed as parameters to this searcher?
        
        // Determine hybrid methods to use

        // logger.debug("Starting Hybrid Search script.");

        String retrieval_method = query.properties().
                getString("hybrid.retrievalMethod", "");
        
        String ranking_method = query.properties().
                getString("hybrid.rankingMethod", "");
        
        String yql_lexical = query.properties().
                getString("yql.lexical", "");

        String yql_tensor = query.properties().
                getString("yql.tensor", "");
        
        String rank_profile_lexical = query.properties().
                getString("ranking.lexical", "");

        String rank_profile_tensor = query.properties().
                getString("ranking.tensor", "");
        
        Integer rrf_k = query.properties().getInteger("hybrid.rrf_k", 60);
        Double alpha = query.properties().getDouble("hybrid.alpha", 0.5);

        // Log fetched variables
        // logger.debug(String.format("Retrieval method found: %s", retrieval_method));
        // logger.debug(String.format("Ranking method found: %s", ranking_method));
        // logger.debug(String.format("YQL lexical found: %s", yql_lexical));
        // logger.debug(String.format("YQL tensor found: %s", yql_tensor));
        // logger.debug(String.format("RRF k found: %d", rrf_k));
        // logger.debug(String.format("alpha found: %.2f", alpha));
        System.out.println(String.format("Retrieval method found: %s", retrieval_method));
        System.out.println(String.format("Ranking method found: %s", ranking_method));
        System.out.println(String.format("YQL lexical found: %s", yql_lexical));
        System.out.println(String.format("YQL tensor found: %s", yql_tensor));
        System.out.println(String.format("Rank Profile lexical found: %s", rank_profile_lexical));
        System.out.println(String.format("Rank Profile tensor found: %s", rank_profile_tensor));
        
        System.out.println(String.format("alpha found: %.2f", alpha));
        System.out.println(String.format("RRF k found: %d", rrf_k));

        System.out.println(String.format("Base Query is: "));
        System.out.println(query.toDetailString());
        

        if (retrieval_method.equals("disjunction")) {
            // Declare result variables
            Result result_lexical, result_tensor;
            Query query_lexical = query.clone();
            query_lexical.properties().set("yql", yql_lexical);
            // TODO: Change to score modifiers when added
            query_lexical.getRanking().setProfile(rank_profile_lexical);
            //logger.debug("LEXICAL QUERY: ");
            //logger.debug(query_lexical.toString());
            System.out.println("LEXICAL QUERY: ");
            System.out.println(query_lexical.toDetailString());
            System.out.println(query_lexical.getModel().getQueryString());
            System.out.println(query_lexical.properties().getString("yql", ""));

            Query query_tensor = query.clone();
            query_tensor.properties().set("yql", yql_tensor);
            // TODO: Change to score modifiers when added
            query_tensor.getRanking().setProfile(rank_profile_tensor);
            //logger.debug("TENSOR QUERY: ");
            //logger.debug(query_tensor.toString());
            System.out.println("TENSOR QUERY: ");
            System.out.println(query_tensor.toDetailString());
            System.out.println(query_tensor.getModel().getQueryString());
            System.out.println(query_tensor.properties().getString("yql", ""));

            // Execute both searches async
            int timeout = 300 * 1000;       // TODO: make configurable
            AsyncExecution async_execution_lexical = new AsyncExecution(execution);
            Future<Result> future_lexical = async_execution_lexical.search(query_lexical);
            AsyncExecution async_execution_tensor = new AsyncExecution(execution);
            Future<Result> future_tensor = async_execution_tensor.search(query_tensor);
            try {
                result_lexical = future_lexical.get(timeout, TimeUnit.MILLISECONDS);
                result_tensor = future_tensor.get(timeout, TimeUnit.MILLISECONDS);
            } catch(TimeoutException | InterruptedException | ExecutionException e) {
                // TODO: Handle timeout better
                throw new RuntimeException(e.toString());
            }

            //logger.debug("LEXICAL RESULTS");
            //logger.debug(result_lexical.toString());
            //logger.debug("TENSOR RESULTS");
            //logger.debug(result_tensor.toString());
            System.out.println("LEXICAL RESULTS");
            System.out.println(result_lexical.toString());
            System.out.println("TENSOR RESULTS");
            System.out.println(result_tensor.toString());

            // TODO: Possible move this outside, when other retrieval methods are available.
            if (ranking_method.equals("rrf")) {
                HitGroup fused_hit_list = rrf(result_tensor.hits(), result_lexical.hits(), rrf_k, alpha);
                //logger.debug("RRF Fused Hit Group");
                //logger.debug(fused_hit_list.toString());
                System.out.println("RRF Fused Hit Group");
                System.out.println(fused_hit_list.toString());
                return new Result(query, fused_hit_list);
            }
        }

        return new Result(query, new HitGroup());
    }

    /**
     * Implement feature score scaling and normalization
     * @param hits_tensor
     * @param hits_lexical
     * @param features
     */
    HitGroup rrf(HitGroup hits_tensor, HitGroup hits_lexical, Integer k, Double alpha) {

        HashMap<String, Double> rrf_scores = new HashMap<>();
        HitGroup result = new HitGroup();
        Double reciprocal_rank, existing_score, new_score;

        //logger.debug("Beginning RRF process.");
        System.out.println("Beginning RRF process.");
        System.out.println("Beginning (empty) result state: ");
        System.out.println(result.toString());

        System.out.println(String.format("alpha is %.2f", alpha));
        System.out.println(String.format("k is %d", k));

        // Iterate through tensor hits list
        //logger.debug(String.format("Tensor result list size: %d", hits_tensor.size()));
        System.out.println(String.format("Tensor result list size: %d", hits_tensor.size()));
        int rank = 1;
        for (Hit hit : hits_tensor) {
            System.out.println(String.format("Raw tensor hit at rank: %d", rank));
            System.out.println(hit.toString());

            reciprocal_rank = alpha * (1.0 / (rank + k));
            rrf_scores.put(hit.getId().toString(), reciprocal_rank);   // Store hit's score via its URI
            hit.setRelevance(reciprocal_rank);                 // Update score to be weighted RR (tensor)
            result.add(hit);
            System.out.println(String.format("Current result size: %d", result.size()));

            System.out.println(String.format("Set relevance to: %.4f", reciprocal_rank));
            System.out.println("Current result state: ");
            System.out.println(result.toString());
            

            //logger.debug(String.format("Modified tensor hit at rank: %d", rank));
            //logger.debug(hit.toString());
            System.out.println(String.format("Modified tensor hit at rank: %d", rank));
            System.out.println(hit.toString());
            rank++;
        }

        // Iterate through lexical hits list
        //logger.debug(String.format("Lexical result list size: %d", hits_lexical.size()));
        System.out.println(String.format("Lexical result list size: %d", hits_lexical.size()));
        rank = 1;
        for (Hit hit : hits_lexical) {
            reciprocal_rank = (1.0-alpha) * (1.0 / (rank + k));

            // Check if score already exists. If so, add to it.
            existing_score = rrf_scores.get(hit.getId().toString());
            if (existing_score == null){
                existing_score = 0.0;
            }
            new_score = existing_score + reciprocal_rank;
            rrf_scores.put(hit.getId().toString(), new_score);
            hit.setRelevance(new_score);      // Update score to be weighted RR (lexical)
            result.add(hit);
            System.out.println(String.format("Current result size: %d", result.size()));

            //logger.debug(String.format("Modified lexical hit at rank: %d", rank));
            //logger.debug(hit.toString());
            System.out.println(String.format("Modified lexical hit at rank: %d", rank));
            System.out.println(hit.toString());
            rank++;
        }

        // sort result
        //logger.debug("Combined list (UNSORTED)");
        //logger.debug(result.toString());
        System.out.println("Combined list (UNSORTED)");
        System.out.println(result.toString());
        result.sort();
        //logger.debug("Combined list (SORTED)");
        //logger.debug(result.toString());
        System.out.println("Combined list (SORTED)");
        System.out.println(result.toString());

        // Only return top hits (max length)
        Integer final_length = Math.max(hits_tensor.size(), hits_lexical.size());
        result.trim(0, final_length);
        //logger.debug("Combined list (TRIMMED)");
        //logger.debug(result.toString());
        System.out.println("Combined list (TRIMMED)");
        System.out.println(result.toString());
        System.out.println(String.format("Current result size: %d", result.size()));

        return result;
    }

    /**
     * Implement feature score scaling and normalization
     * @param hits
     * @param features
     */
    void normalize(HitGroup hits, String[] features) {
        // Min - Max normalization
        double[] minValues = new double[features.length];
        double[] maxValues = new double[features.length];
        for(int i = 0; i < features.length;i++) {
            minValues[i] = Double.MAX_VALUE;
            maxValues[i] = Double.MIN_VALUE;
        }

        //Find min and max value in the re-ranking window
        for (Hit hit : hits) {
            if(hit.isAuxiliary())
                continue;
            FeatureData featureData = (FeatureData) hit.getField(MATCH_FEATURES_FIELD);
            if(featureData == null)
                throw new RuntimeException("No feature data in hit - wrong rank profile used?");
            for(int i = 0; i < features.length; i++) {
                // loop through bm25, colbert_maxsim
                double score = featureData.getDouble(features[i]);
                if(score < minValues[i])
                    minValues[i] = score;
                if(score > maxValues[i])
                    maxValues[i] = score;
            }
        }
        //re-score using normalized value
        for (Hit hit : hits) {
            if(hit.isAuxiliary())
                continue;
            FeatureData featureData = (FeatureData) hit.getField(MATCH_FEATURES_FIELD);
            double finalScore = 0;
            for(int i = 0; i < features.length; i++) {
                // loop through bm25, colbert_maxsim
                double score = featureData.getDouble(features[i]);
                // No alpha implemented yet. can be added here
                finalScore += (score - minValues[i]) / (maxValues[i] - minValues[i]);
            }
            // average bm25 and colbert_maxsim. 
            finalScore = finalScore / features.length;
            hit.setRelevance(finalScore);
        }
    }
}