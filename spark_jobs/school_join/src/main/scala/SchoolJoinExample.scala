import org.apache.spark.sql.SparkSession

object SchoolJoinExample {
  def main(args: Array[String]): Unit = {

    // Initialize SparkSession
    val spark = SparkSession.builder()
      .appName("StudentSchoolTeacherJoin")
      .master("local[*]")
      .getOrCreate()

    import spark.implicits._

    // 1. Create Students DataFrame (100 rows)
    // Using modulo to assign each student to one of 5 schools (IDs 1 through 5)
    val studentsDF = (1 to 100).map { i =>
      (i, s"Student_$i", (i % 5) + 1)
    }.toDF("student_id", "student_name", "school_id")

    // 2. Create Schools DataFrame
    val schoolsDF = Seq(
      (1, "Alpha Academy"),
      (2, "Beta High"),
      (3, "Gamma Institute"),
      (4, "Delta Tech"),
      (5, "Epsilon Public")
    ).toDF("school_id", "school_name")

    // 3. Create Teachers DataFrame
    // Assigning one primary teacher per school for the join
    val teachersDF = Seq(
      (101, "Mr. Turing", 1),
      (102, "Ms. Lovelace", 2),
      (103, "Dr. Codd", 3),
      (104, "Mr. Babbage", 4),
      (105, "Prof. Neumann", 5)
    ).toDF("teacher_id", "teacher_name", "school_id")

    // 4. Join the DataFrames
    // Using Seq("school_id") avoids duplicate school_id columns in the final DataFrame
    val joinedDF = studentsDF
      .join(schoolsDF, Seq("school_id"), "inner")
      .join(teachersDF, Seq("school_id"), "inner")

    // 5. Print the total count
    val totalCount = joinedDF.count()
    println(s"Total record count after joins: $totalCount")

    // 6. Show the first 10 rows
    joinedDF.show(10, truncate = false)

    // Stop the Spark context
    spark.stop()
  }
}
