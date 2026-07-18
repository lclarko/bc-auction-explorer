export type paths = {
    "/api/categories": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Categories */
        get: operations["list_categories_api_categories_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/listings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Listings */
        get: operations["list_listings_api_listings_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/listings/{source_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Listing */
        get: operations["get_listing_api_listings__source_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/locations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Locations */
        get: operations["list_locations_api_locations_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/scrape-status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Scrape Status */
        get: operations["scrape_status_api_scrape_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
};
export type webhooks = Record<string, never>;
export type components = {
    schemas: {
        /** ApiError */
        ApiError: {
            /** Code */
            code: string;
            /** Details */
            details?: unknown | null;
            /** Message */
            message: string;
        };
        /**
         * AuctionStatus
         * @enum {string}
         */
        AuctionStatus: "open" | "closed" | "withdrawn" | "unknown";
        /** ErrorResponse */
        ErrorResponse: {
            error: components["schemas"]["ApiError"];
        };
        /** Facet */
        Facet: {
            /** Count */
            count: number;
            /** Value */
            value: string;
        };
        /** FacetList */
        FacetList: {
            /** Items */
            items: components["schemas"]["Facet"][];
        };
        /**
         * ListingAvailability
         * @enum {string}
         */
        ListingAvailability: "active" | "scheduled_closing_passed" | "closed" | "withdrawn" | "unknown";
        /** ListingDetail */
        ListingDetail: {
            availability: components["schemas"]["ListingAvailability"];
            /** Bid Count */
            bid_count?: number | null;
            /** Canonical Source Url */
            canonical_source_url: string;
            /** Category */
            category?: string | null;
            /** Category Canonical */
            category_canonical?: string | null;
            /** Category Raw */
            category_raw?: string | null;
            /** Closed At */
            closed_at?: string | null;
            /** Closing At */
            closing_at?: string | null;
            /** Current Bid */
            current_bid?: string | null;
            /** Description */
            description?: string | null;
            /**
             * First Seen At
             * Format: date-time
             */
            first_seen_at: string;
            /**
             * Image Urls
             * @default []
             */
            image_urls: string[];
            /**
             * Last Changed At
             * Format: date-time
             */
            last_changed_at: string;
            /**
             * Last Seen At
             * Format: date-time
             */
            last_seen_at: string;
            /** Location */
            location?: string | null;
            /** Location Canonical */
            location_canonical?: string | null;
            location_normalization_status?: components["schemas"]["LocationStatus"] | null;
            /** Location Qualifier */
            location_qualifier?: string | null;
            /** Location Raw */
            location_raw?: string | null;
            /** Minimum Bid */
            minimum_bid?: string | null;
            /**
             * Observed At
             * Format: date-time
             */
            observed_at: string;
            /** Pickup Details */
            pickup_details?: string | null;
            /** Source Id */
            source_id: string;
            /** Starting Bid */
            starting_bid?: string | null;
            status: components["schemas"]["AuctionStatus"];
            /** Status Raw */
            status_raw?: string | null;
            /** Title */
            title: string;
        };
        /** ListingPage */
        ListingPage: {
            /** Items */
            items: components["schemas"]["ListingSummary"][];
            page_info: components["schemas"]["PageInfo"];
        };
        /**
         * ListingSort
         * @enum {string}
         */
        ListingSort: "closing_soon" | "closing_latest" | "price_low" | "price_high" | "newest_seen" | "most_bids";
        /** ListingSummary */
        ListingSummary: {
            availability: components["schemas"]["ListingAvailability"];
            /** Bid Count */
            bid_count?: number | null;
            /** Canonical Source Url */
            canonical_source_url: string;
            /** Category */
            category?: string | null;
            /** Closed At */
            closed_at?: string | null;
            /** Closing At */
            closing_at?: string | null;
            /** Current Bid */
            current_bid?: string | null;
            /**
             * First Seen At
             * Format: date-time
             */
            first_seen_at: string;
            /**
             * Image Urls
             * @default []
             */
            image_urls: string[];
            /**
             * Last Changed At
             * Format: date-time
             */
            last_changed_at: string;
            /**
             * Last Seen At
             * Format: date-time
             */
            last_seen_at: string;
            /** Location */
            location?: string | null;
            /** Location Qualifier */
            location_qualifier?: string | null;
            /** Minimum Bid */
            minimum_bid?: string | null;
            /**
             * Observed At
             * Format: date-time
             */
            observed_at: string;
            /** Source Id */
            source_id: string;
            /** Starting Bid */
            starting_bid?: string | null;
            status: components["schemas"]["AuctionStatus"];
            /** Title */
            title: string;
        };
        /**
         * ListingView
         * @enum {string}
         */
        ListingView: "active" | "ended" | "all";
        /**
         * LocationStatus
         * @enum {string}
         */
        LocationStatus: "exact" | "alias" | "unknown";
        /** PageInfo */
        PageInfo: {
            /** Page */
            page: number;
            /** Page Size */
            page_size: number;
            /** Total Items */
            total_items: number;
            /** Total Pages */
            total_pages: number;
        };
        /**
         * ScrapeRunState
         * @enum {string}
         */
        ScrapeRunState: "running" | "succeeded" | "partial" | "failed";
        /** ScrapeRunSummary */
        ScrapeRunSummary: {
            /** Finished At */
            finished_at?: string | null;
            /** Item Failures */
            item_failures: number;
            /** Items Created */
            items_created: number;
            /** Items Seen */
            items_seen: number;
            /** Items Updated */
            items_updated: number;
            /** Mode */
            mode: string;
            /** Observations Created */
            observations_created: number;
            /** Pages Visited */
            pages_visited: number;
            /** Rate Limit Responses */
            rate_limit_responses: number;
            /** Requested Limit */
            requested_limit: number;
            /** Source Request Duration Ms */
            source_request_duration_ms: number;
            /** Source Request Wait Duration Ms */
            source_request_wait_duration_ms: number;
            /** Source Requests */
            source_requests: number;
            /** Source Responses */
            source_responses: number;
            /** Source Retries */
            source_retries: number;
            /** Source Retry Wait Duration Ms */
            source_retry_wait_duration_ms: number;
            /** Source Transport Errors */
            source_transport_errors: number;
            /**
             * Started At
             * Format: date-time
             */
            started_at: string;
            status: components["schemas"]["ScrapeRunState"];
        };
        /** ScrapeStatus */
        ScrapeStatus: {
            /** Latest Listing Seen At */
            latest_listing_seen_at?: string | null;
            latest_run?: components["schemas"]["ScrapeRunSummary"] | null;
            latest_successful_run?: components["schemas"]["ScrapeRunSummary"] | null;
            /** Listing Count */
            listing_count: number;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
};
export type $defs = Record<string, never>;
export interface operations {
    list_categories_api_categories_get: {
        parameters: {
            query?: {
                view?: components["schemas"]["ListingView"];
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FacetList"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    list_listings_api_listings_get: {
        parameters: {
            query?: {
                keyword?: string | null;
                location?: string | null;
                category?: string | null;
                min_price?: number | string | null;
                max_price?: number | string | null;
                closing_after?: string | null;
                closing_before?: string | null;
                view?: components["schemas"]["ListingView"];
                sort?: components["schemas"]["ListingSort"] | null;
                page?: number;
                page_size?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ListingPage"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    get_listing_api_listings__source_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                source_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ListingDetail"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    list_locations_api_locations_get: {
        parameters: {
            query?: {
                view?: components["schemas"]["ListingView"];
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FacetList"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    scrape_status_api_scrape_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ScrapeStatus"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
}
