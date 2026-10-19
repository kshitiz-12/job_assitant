"""Skill vocabulary shared by the scraper and the matcher.

One list, compiled once. If the scraper and the chat disagreed about whether
"JS" meant JavaScript, the match scores would be fiction.
"""

from __future__ import annotations

import re

# (canonical name, aliases). Longer phrases are sorted ahead of short ones
# at compile time. "react" is a prefix of "react native"; if the short form
# won, those jobs would lose the more specific skill.
SKILL_ALIASES: list[tuple[str, tuple[str, ...]]] = [
    ("react native", ("react native", "react-native")),
    ("next.js", ("next.js", "nextjs", "next js")),
    ("node.js", ("node.js", "nodejs", "node js")),
    ("javascript", ("javascript", "java script")),
    ("typescript", ("typescript",)),
    ("react", ("react.js", "reactjs", "react")),
    ("vue", ("vue.js", "vuejs", "vue")),
    ("angular", ("angularjs", "angular.js", "angular")),
    ("svelte", ("svelte")),
    ("redux", ("redux",)),
    ("express", ("express.js", "expressjs")),
    ("nestjs", ("nestjs", "nest.js")),
    ("python", ("python",)),
    ("django", ("django",)),
    ("flask", ("flask",)),
    ("fastapi", ("fastapi", "fast api")),
    ("pandas", ("pandas",)),
    ("numpy", ("numpy",)),
    ("scikit-learn", ("scikit-learn", "sklearn")),
    ("pytorch", ("pytorch",)),
    ("tensorflow", ("tensorflow",)),
    ("machine learning", ("machine learning",)),
    ("deep learning", ("deep learning",)),
    ("computer vision", ("computer vision",)),
    ("nlp", ("natural language processing", "nlp")),
    ("llm", ("large language models", "large language model", "llms", "llm")),
    ("java", ("java",)),
    ("kotlin", ("kotlin",)),
    ("scala", ("scala",)),
    ("spring", ("spring boot", "springboot", "spring framework", "spring")),
    ("c++", ("c++",)),
    ("c#", ("c#",)),
    (".net", ("asp.net", ".net", "dotnet")),
    ("go", ("golang",)),
    ("rust", ("rust",)),
    ("ruby", ("ruby on rails", "ruby")),
    ("rails", ("rails",)),
    ("php", ("php",)),
    ("laravel", ("laravel",)),
    ("swift", ("swift",)),
    ("ios", ("ios",)),
    ("android", ("android",)),
    ("flutter", ("flutter",)),
    ("sql", ("sql",)),
    ("postgresql", ("postgresql", "postgres")),
    ("mysql", ("mysql",)),
    ("sqlite", ("sqlite",)),
    ("mongodb", ("mongodb", "mongo db")),
    ("redis", ("redis",)),
    ("elasticsearch", ("elasticsearch",)),
    ("dynamodb", ("dynamodb", "dynamo db")),
    ("cassandra", ("cassandra",)),
    ("graphql", ("graphql",)),
    ("grpc", ("grpc",)),
    ("kafka", ("kafka",)),
    ("rabbitmq", ("rabbitmq",)),
    ("docker", ("docker",)),
    ("kubernetes", ("kubernetes", "k8s")),
    ("helm", ("helm",)),
    ("terraform", ("terraform",)),
    ("ansible", ("ansible",)),
    ("linux", ("linux",)),
    ("bash", ("bash",)),
    ("powershell", ("powershell",)),
    ("aws", ("amazon web services", "aws")),
    ("gcp", ("google cloud platform", "google cloud", "gcp")),
    ("azure", ("microsoft azure", "azure")),
    ("aws lambda", ("aws lambda",)),
    ("serverless", ("serverless",)),
    ("cloudformation", ("cloudformation",)),
    ("git", ("git",)),
    ("html", ("html5", "html")),
    ("css", ("css3", "css")),
    ("tailwind", ("tailwind css", "tailwind")),
    ("sass", ("scss", "sass")),
    ("webpack", ("webpack",)),
    ("figma", ("figma",)),
    ("sketch", ("sketch",)),
    ("photoshop", ("photoshop",)),
    ("illustrator", ("illustrator",)),
    ("jira", ("jira",)),
    ("agile", ("agile",)),
    ("scrum", ("scrum",)),
    ("rest", ("restful", "rest api", "rest")),
    ("ci/cd", ("continuous integration", "ci/cd", "cicd")),
    ("jenkins", ("jenkins",)),
    ("github actions", ("github actions",)),
    ("selenium", ("selenium",)),
    ("cypress", ("cypress",)),
    ("jest", ("jest",)),
    ("pytest", ("pytest",)),
    ("spark", ("apache spark", "pyspark", "spark")),
    ("hadoop", ("hadoop",)),
    ("airflow", ("airflow",)),
    ("dbt", ("dbt",)),
    ("snowflake", ("snowflake",)),
    ("bigquery", ("bigquery", "big query")),
    ("redshift", ("redshift",)),
    ("databricks", ("databricks",)),
    ("tableau", ("tableau",)),
    ("power bi", ("power bi", "powerbi")),
    ("looker", ("looker",)),
    ("excel", ("microsoft excel", "ms excel", "excel")),
    ("salesforce", ("salesforce",)),
    ("hubspot", ("hubspot",)),
    ("seo", ("search engine optimization", "seo")),
    ("google analytics", ("google analytics",)),
    ("google ads", ("google ads",)),
    ("product management", ("product management",)),
    ("project management", ("project management",)),
    ("ui/ux", ("ui/ux", "user experience", "user interface")),
    ("copywriting", ("copywriting",)),
    ("content marketing", ("content marketing",)),
    ("wordpress", ("wordpress",)),
    ("shopify", ("shopify",)),
    ("webflow", ("webflow",)),
    ("contentful", ("contentful",)),
    ("firebase", ("firebase",)),
    ("supabase", ("supabase",)),
    ("prisma", ("prisma",)),
    ("sqlalchemy", ("sqlalchemy",)),
    ("microservices", ("microservices", "micro-services")),
    ("oauth", ("oauth", "oAuth")),
    ("prometheus", ("prometheus",)),
    ("grafana", ("grafana",)),
    ("datadog", ("datadog",)),
    ("solidity", ("solidity",)),
    ("matlab", ("matlab",)),
    ("sap", ("sap",)),
    ("oracle", ("oracle database", "oracle")),
    ("hive", ("apache hive", "hive")),
    ("flink", ("apache flink", "flink")),
    ("trino", ("trino", "presto")),
    ("unity", ("unity3d", "unity engine")),
    ("unreal", ("unreal engine",)),
    ("canva", ("canva",)),
    ("framer", ("framer",)),
    ("strapi", ("strapi",)),
    ("pulumi", ("pulumi",)),
    ("active directory", ("active directory",)),
    ("cybersecurity", ("cybersecurity", "information security")),
    ("penetration testing", ("penetration testing", "pen testing")),
    ("data analysis", ("data analysis",)),
    ("statistics", ("statistics",)),
    ("a/b testing", ("a/b testing", "ab testing")),
]

# These show up on almost every posting. They still get stored on the resume,
# but they barely move the match score — otherwise "git" ties a designer to a backend role.
WEAK_SKILLS = frozenset({
    "git",
    "jira",
    "agile",
    "scrum",
    "excel",
    "rest",
    "ci/cd",
    "html",
    "css",
})

# A parent skill quietly implies the platform it sits on.
IMPLIES = {
    "react native": ("react",),
    "next.js": ("react",),
    "django": ("python",),
    "flask": ("python",),
    "fastapi": ("python",),
    "spring": ("java",),
    "express": ("node.js",),
    "nestjs": ("node.js",),
    "pandas": ("python",),
    "pytorch": ("python", "machine learning"),
    "tensorflow": ("python", "machine learning"),
    "rails": ("ruby",),
}

_LABELS = {
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "node.js": "Node.js",
    "next.js": "Next.js",
    "postgresql": "PostgreSQL",
    "mysql": "MySQL",
    "mongodb": "MongoDB",
    "graphql": "GraphQL",
    "aws": "AWS",
    "gcp": "GCP",
    "css": "CSS",
    "html": "HTML",
    "sql": "SQL",
    "php": "PHP",
    "ios": "iOS",
    "android": "Android",
    "c++": "C++",
    "c#": "C#",
    ".net": ".NET",
    "go": "Go",
    "nlp": "NLP",
    "llm": "LLM",
    "ui/ux": "UI/UX",
    "ci/cd": "CI/CD",
    "rest": "REST",
    "grpc": "gRPC",
    "scikit-learn": "scikit-learn",
    "pytorch": "PyTorch",
    "tensorflow": "TensorFlow",
    "dynamodb": "DynamoDB",
    "elasticsearch": "Elasticsearch",
    "bigquery": "BigQuery",
    "power bi": "Power BI",
    "github actions": "GitHub Actions",
    "aws lambda": "AWS Lambda",
    "nestjs": "NestJS",
    "fastapi": "FastAPI",
    "oauth": "OAuth",
    "sap": "SAP",
    "sqlite": "SQLite",
    "redis": "Redis",
    "linux": "Linux",
    "numpy": "NumPy",
    "dbt": "dbt",
    "seo": "SEO",
    "a/b testing": "A/B testing",
    "google analytics": "Google Analytics",
    "google ads": "Google Ads",
    "active directory": "Active Directory",
    "computer vision": "Computer Vision",
    "deep learning": "Deep Learning",
    "machine learning": "Machine Learning",
    "data analysis": "Data Analysis",
    "product management": "Product Management",
    "project management": "Project Management",
    "content marketing": "Content Marketing",
    "penetration testing": "Penetration Testing",
    "cybersecurity": "Cybersecurity",
    "react native": "React Native",
    "react": "React",
    "vue": "Vue",
    "angular": "Angular",
    "python": "Python",
    "java": "Java",
    "kotlin": "Kotlin",
    "scala": "Scala",
    "rust": "Rust",
    "ruby": "Ruby",
    "rails": "Rails",
    "swift": "Swift",
    "flutter": "Flutter",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "terraform": "Terraform",
    "azure": "Azure",
    "figma": "Figma",
    "tailwind": "Tailwind",
    "redux": "Redux",
    "django": "Django",
    "flask": "Flask",
    "spring": "Spring",
    "kafka": "Kafka",
    "spark": "Spark",
    "airflow": "Airflow",
    "snowflake": "Snowflake",
    "databricks": "Databricks",
    "tableau": "Tableau",
    "salesforce": "Salesforce",
    "hubspot": "HubSpot",
    "firebase": "Firebase",
    "supabase": "Supabase",
    "prisma": "Prisma",
    "grafana": "Grafana",
    "datadog": "Datadog",
    "jenkins": "Jenkins",
    "cypress": "Cypress",
    "jest": "Jest",
    "pytest": "pytest",
    "git": "Git",
    "jira": "Jira",
    "photoshop": "Photoshop",
    "illustrator": "Illustrator",
    "wordpress": "WordPress",
    "shopify": "Shopify",
    "webflow": "Webflow",
    "matlab": "MATLAB",
    "canva": "Canva",
    "solidity": "Solidity",
    "oracle": "Oracle",
    "looker": "Looker",
    "redshift": "Redshift",
    "ansible": "Ansible",
    "bash": "Bash",
    "powershell": "PowerShell",
    "microservices": "Microservices",
    "serverless": "Serverless",
    "laravel": "Laravel",
    "svelte": "Svelte",
    "express": "Express",
    "webpack": "Webpack",
    "sass": "Sass",
    "helm": "Helm",
    "prometheus": "Prometheus",
    "contentful": "Contentful",
    "strapi": "Strapi",
    "framer": "Framer",
    "unity": "Unity",
    "unreal": "Unreal",
    "flink": "Flink",
    "trino": "Trino",
    "hive": "Hive",
    "cassandra": "Cassandra",
    "rabbitmq": "RabbitMQ",
    "sqlalchemy": "SQLAlchemy",
    "selenium": "Selenium",
    "sketch": "Sketch",
    "agile": "Agile",
    "scrum": "Scrum",
    "excel": "Excel",
    "statistics": "Statistics",
    "copywriting": "Copywriting",
    "pulumi": "Pulumi",
    "cloudformation": "CloudFormation",
}


def skill_label(name: str) -> str:
    if name in _LABELS:
        return _LABELS[name]
    if name.isupper() or any(ch.isupper() for ch in name):
        return name
    return name.title()


def _compile() -> tuple[re.Pattern[str], dict[str, str]]:
    pairs: list[tuple[str, str]] = []
    for canon, aliases in SKILL_ALIASES:
        # A one-letter tuple mistake ("svelte",) vs ("svelte") would blow up
        # the regex. Aliases are always a tuple of strings.
        if isinstance(aliases, str):
            aliases = (aliases,)
        for alias in aliases:
            pairs.append((alias.lower(), canon))
    # Longest alias first. Python's "|" is left-first, not longest-match.
    pairs.sort(key=lambda item: len(item[0]), reverse=True)
    lookup: dict[str, str] = {}
    alts: list[str] = []
    seen_alias: set[str] = set()
    for alias, canon in pairs:
        if alias in seen_alias:
            continue
        seen_alias.add(alias)
        lookup[alias] = canon
        alts.append(re.escape(alias))
    # Letter lookahead, not alnum: "c++17" should still count as C++.
    # "java" does not match inside "javascript" because "s" is a letter.
    pattern = re.compile(
        r"(?<![a-z0-9])(" + "|".join(alts) + r")(?![a-z])",
        re.IGNORECASE,
    )
    return pattern, lookup


_PATTERN, _LOOKUP = _compile()


def extract_skills(text: str, limit: int = 24) -> list[str]:
    """Return canonical skills in the order they first appear."""
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for match in _PATTERN.finditer(text):
        canon = _LOOKUP.get(match.group(1).lower())
        if not canon or canon in seen:
            continue
        seen.add(canon)
        found.append(canon)
        if len(found) >= limit:
            break
    if len(found) < limit:
        for parent, extras in IMPLIES.items():
            if parent not in seen:
                continue
            for extra in extras:
                if extra in seen:
                    continue
                seen.add(extra)
                found.append(extra)
                if len(found) >= limit:
                    return found
    return found
