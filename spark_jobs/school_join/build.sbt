name         := "school-join"
version      := "1.0"
scalaVersion := "2.12.18"

// Spark is provided at runtime by the cluster / spark-submit
libraryDependencies += "org.apache.spark" %% "spark-sql" % "3.5.0" % "provided"

// Put the JAR in a predictable location so the DAG can glob for it
assembly / assemblyOutputPath := baseDirectory.value / "target" / "school-join.jar"
